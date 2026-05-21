"""Generate, edit, and persist reviewed application fill plans."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from src import llm_client
from src.application_package_quality import is_sensitive_or_user_decision_field
from src.paths import application_fill_plan_paths, runtime_application_fill_plan_path
from src.prompt_templates import get_prompt
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    CandidateProfile,
    ConfidenceLevel,
)
from src.storage import load_model, save_model

DEFAULT_SUBMIT_GUARD_LABELS = [
    "Weiter & Pruefen",
    "Weiter & Prüfen",
    "Absenden",
    "Senden",
    "Submit",
    "Apply",
    "Bewerbung absenden",
]


@dataclass(frozen=True)
class FillPlanTargetField:
    """Application field that still needs a safe value mapping."""

    label: str
    name: str = ""
    required: bool = False
    input_type: str = ""
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    kind: str = "field"
    default_reason: str = "No safe candidate or reviewed package value is available."


class ApplicationFieldMappingSuggestion(BaseModel):
    """Suggested value for one unresolved application field."""

    label: str
    value: str = ""
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    reason: str = ""


class LLMApplicationFieldMappingResponse(BaseModel):
    """Structured response for semantic application field mapping."""

    suggestions: list[ApplicationFieldMappingSuggestion] = []


ApplicationFieldMapper = Callable[
    [CandidateProfile, ApplicationRequirements, ApplicationPackage, list[FillPlanTargetField]],
    list[ApplicationFieldMappingSuggestion],
]


def generate_application_fill_plan(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    *,
    semantic_mapper: ApplicationFieldMapper | None = None,
) -> ApplicationFillPlan:
    """Create a conservative draft fill plan from reviewed application data."""

    field_values: list[ApplicationFillFieldValue] = []
    blocked_fields: list[ApplicationFillBlockedField] = []
    unresolved_fields: list[FillPlanTargetField] = []
    used_labels: set[str] = set()

    for field in [*requirements.profile_fields, *requirements.custom_form_fields]:
        key = _field_key(field.label or field.name)
        if _should_block_field(key):
            blocked_fields.append(_blocked_from_form_field(field, "Field requires user review."))
            continue

        candidate_value = _candidate_value_for_field(candidate_profile, field)
        if candidate_value:
            field_values.append(
                ApplicationFillFieldValue(
                    label=field.label,
                    name=field.name,
                    value=candidate_value,
                    required=field.required,
                    input_type=field.input_type,
                    source=_candidate_source_for_field(field),
                    confidence="high",
                )
            )
            used_labels.add(key)
            continue

        package_value = _package_answer_for_label(package, field.label)
        if package_value:
            field_values.append(
                ApplicationFillFieldValue(
                    label=field.label,
                    name=field.name,
                    value=package_value,
                    required=field.required,
                    input_type=field.input_type,
                    source="application_package.form_answer",
                    confidence="medium",
                )
            )
            used_labels.add(key)
            continue

        reason = "No safe candidate or reviewed package value is available."
        unresolved_fields.append(_target_from_form_field(field, default_reason=reason))

    for question in requirements.screening_questions:
        key = _field_key(question.question)
        if key in used_labels or _should_block_field(key):
            blocked_fields.append(
                _blocked_from_screening_question(question, "Field requires user review.")
            )
            continue

        package_value = _package_answer_for_label(package, question.question)
        if package_value:
            field_values.append(
                ApplicationFillFieldValue(
                    label=question.question,
                    value=package_value,
                    required=question.required,
                    input_type=question.input_type,
                    source="application_package.form_answer",
                    confidence="medium",
                )
            )
        else:
            unresolved_fields.append(
                _target_from_screening_question(
                    question,
                    default_reason="No reviewed package answer is available.",
                )
            )

    _apply_semantic_mapping(
        candidate_profile,
        requirements,
        package,
        semantic_mapper,
        unresolved_fields,
        field_values,
        blocked_fields,
    )

    for requirement in [
        *requirements.consent_requirements,
        *requirements.privacy_login_ats_gates,
    ]:
        blocked_fields.append(
            ApplicationFillBlockedField(
                label=requirement.label,
                reason="Consent, privacy, login, or ATS gate requires user review.",
                required=requirement.required,
                source=requirement.evidence,
                confidence=requirement.confidence,
            )
        )

    return ApplicationFillPlan(
        job_id=requirements.job_id,
        apply_url=requirements.apply_url,
        review_status="draft",
        field_values=_dedupe_field_values(field_values),
        upload_files=_build_upload_files(candidate_profile, requirements),
        blocked_fields=_dedupe_blocked_fields(blocked_fields),
        submit_guard_labels=DEFAULT_SUBMIT_GUARD_LABELS,
    )


def apply_fill_plan_edits(
    fill_plan: ApplicationFillPlan,
    values_by_label: dict[str, str],
) -> ApplicationFillPlan:
    """Return a fill plan with reviewer-edited field values."""

    edited = fill_plan.model_copy(deep=True)
    for field in edited.field_values:
        if field.label not in values_by_label:
            continue
        field.value = values_by_label[field.label].strip()
        field.source = field.source or "manual_review"
    edited.review_status = "draft"
    return edited


def mark_application_fill_plan_reviewed(fill_plan: ApplicationFillPlan) -> ApplicationFillPlan:
    """Return a fill plan marked as reviewed."""

    reviewed = fill_plan.model_copy(deep=True)
    reviewed.review_status = "reviewed"
    return reviewed


def save_application_fill_plan(base_dir: Path | str, fill_plan: ApplicationFillPlan) -> Path:
    """Persist a fill plan JSON for one job workspace."""

    target = runtime_application_fill_plan_path(base_dir, fill_plan.job_id)
    save_model(target, fill_plan)
    return target


def load_application_fill_plan(base_dir: Path | str, job_id: str) -> ApplicationFillPlan | None:
    """Load a fill plan from runtime data or checked-in templates."""

    runtime_path, template_path = application_fill_plan_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationFillPlan, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationFillPlan, default=None)
    return None


def map_application_fields_with_llm(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    target_fields: list[FillPlanTargetField],
) -> list[ApplicationFieldMappingSuggestion]:
    """Use structured AI to map unresolved safe fields to candidate evidence."""

    if not target_fields:
        return []

    response = llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": get_prompt("application_field_mapping", "map_fields", "system"),
            },
            {
                "role": "user",
                "content": get_prompt(
                    "application_field_mapping",
                    "map_fields",
                    "user",
                    candidate_evidence_json=_to_json(_candidate_evidence(candidate_profile)),
                    package_answers_json=_to_json(_package_form_answers(package)),
                    target_fields_json=_to_json(
                        [field.__dict__ for field in target_fields]
                    ),
                ),
            },
        ],
        text_format=LLMApplicationFieldMappingResponse,
        operation="AI application field mapping",
        profile=llm_client.APPLICATION_FIELD_MAPPING_PROFILE,
    )
    return response.suggestions


def _apply_semantic_mapping(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    semantic_mapper: ApplicationFieldMapper | None,
    unresolved_fields: list[FillPlanTargetField],
    field_values: list[ApplicationFillFieldValue],
    blocked_fields: list[ApplicationFillBlockedField],
) -> None:
    if not unresolved_fields:
        return

    suggestions_by_label: dict[str, ApplicationFieldMappingSuggestion] = {}
    if semantic_mapper is not None:
        suggestions_by_label = {
            _field_key(suggestion.label): suggestion
            for suggestion in semantic_mapper(
                candidate_profile,
                requirements,
                package,
                unresolved_fields,
            )
        }

    for target in unresolved_fields:
        suggestion = suggestions_by_label.get(_field_key(target.label))
        if suggestion is not None and suggestion.value.strip():
            field_values.append(
                ApplicationFillFieldValue(
                    label=target.label,
                    name=target.name,
                    value=suggestion.value.strip(),
                    required=target.required,
                    input_type=target.input_type,
                    source=suggestion.source or "application_field_mapping",
                    confidence=suggestion.confidence,
                )
            )
            continue

        reason = target.default_reason
        if suggestion is not None and suggestion.reason.strip():
            reason = suggestion.reason.strip()
        blocked_fields.append(_blocked_from_target_field(target, reason))


def _candidate_value_for_field(
    candidate_profile: CandidateProfile,
    field: ApplicationFormField,
) -> str:
    identity = candidate_profile.candidate_profile.cv_extracted.identity
    first_name, last_name = _split_full_name(identity.full_name)
    label = _field_key(field.label or field.name)
    location = identity.location.strip()

    if any(term in label for term in ("anrede", "salutation", "title")):
        return identity.salutation.strip()
    if any(term in label for term in ("vorname", "first name", "given name")):
        return first_name
    if any(term in label for term in ("nachname", "last name", "surname", "family name")):
        return last_name
    if any(term in label for term in ("e-mail", "email", "mail adresse", "e-mail-adresse")):
        return identity.email.strip()
    if any(term in label for term in ("telefon", "phone", "mobile", "handy")):
        return identity.phone.strip()
    if label in {"ort", "city", "wohnort"}:
        return identity.city.strip() or _city_from_location(location)
    if "postleitzahl" in label or "postal" in label or "zip" in label:
        return identity.postal_code.strip()
    if any(term in label for term in ("straße", "strasse", "street", "address", "hausanschrift")):
        return identity.street_address.strip()
    if "land" in label and "wohn" in label:
        return identity.country.strip() or _country_from_location(location)
    if "linkedin" in label:
        return identity.linkedin_url.strip()
    if "github" in label:
        return identity.github_url.strip()
    if "portfolio" in label or "website" in label:
        return identity.portfolio_url.strip()
    return ""


def _candidate_source_for_field(field: ApplicationFormField) -> str:
    label = _field_key(field.label or field.name)
    if any(term in label for term in ("anrede", "salutation", "title")):
        return "candidate_profile.cv_extracted.identity.salutation"
    if any(term in label for term in ("vorname", "first name", "nachname", "last name")):
        return "candidate_profile.cv_extracted.identity.full_name"
    if "mail" in label:
        return "candidate_profile.cv_extracted.identity.email"
    if any(term in label for term in ("telefon", "phone", "mobile", "handy")):
        return "candidate_profile.cv_extracted.identity.phone"
    if "postleitzahl" in label or "postal" in label or "zip" in label:
        return "candidate_profile.cv_extracted.identity.postal_code"
    if any(term in label for term in ("straße", "strasse", "street", "address", "hausanschrift")):
        return "candidate_profile.cv_extracted.identity.street_address"
    if label in {"ort", "city", "wohnort"}:
        return "candidate_profile.cv_extracted.identity.city"
    if "land" in label and "wohn" in label:
        return "candidate_profile.cv_extracted.identity.country"
    if "linkedin" in label:
        return "candidate_profile.cv_extracted.identity.linkedin_url"
    if "github" in label:
        return "candidate_profile.cv_extracted.identity.github_url"
    if "portfolio" in label or "website" in label:
        return "candidate_profile.cv_extracted.identity.portfolio_url"
    return "candidate_profile.cv_extracted.identity.location"


def _build_upload_files(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
) -> list[ApplicationFillUploadFile]:
    cv_path = candidate_profile.candidate_profile.source_documents.cv.file_path.strip()
    if not cv_path:
        return []

    required = any(item.required for item in requirements.required_documents)
    label = "CV / Resume"
    for item in [*requirements.required_documents, *requirements.upload_expectations]:
        item_text = _field_key(" ".join([item.label, item.evidence, *item.constraints]))
        upload_terms = ("cv", "resume", "lebenslauf", "bewerbungsunterlagen")
        if any(term in item_text for term in upload_terms):
            label = item.label
            required = required or item.required
            break

    return [
        ApplicationFillUploadFile(
            label=label,
            file_path=cv_path,
            document_type="cv",
            required=required,
            source="candidate_profile.source_documents.cv.file_path",
            confidence="high",
        )
    ]


def _package_answer_for_label(package: ApplicationPackage, label: str) -> str:
    target = _field_key(label)
    for artifact in package.artifacts:
        if artifact.type != "form_answer":
            continue
        candidates = [
            artifact.label,
            artifact.source_prompt or "",
            artifact.source_requirement or "",
        ]
        if any(_field_key(candidate) == target for candidate in candidates):
            return artifact.content.strip()
    return ""


def _should_block_field(normalized_label: str) -> bool:
    decision_terms = (
        "legal",
        "rechtlich",
        "visa",
        "sponsorship",
        "work authorization",
        "arbeitserlaubnis",
        "recommendation",
        "referral",
        "empfehlung",
        "internal",
        "intern",
        "employee",
        "mitarbeiter",
        "disability",
        "behinderung",
        "schwerbehinderung",
        "gleichstellung",
        "consent",
        "privacy",
        "datenschutz",
        "einwilligung",
    )
    return is_sensitive_or_user_decision_field(normalized_label) or any(
        term in normalized_label for term in decision_terms
    )


def _blocked_from_form_field(
    field: ApplicationFormField,
    reason: str,
) -> ApplicationFillBlockedField:
    return ApplicationFillBlockedField(
        label=field.label,
        name=field.name,
        reason=reason,
        required=field.required,
        input_type=field.input_type,
        source=field.evidence,
        confidence=field.confidence,
    )


def _blocked_from_screening_question(
    question: ApplicationScreeningQuestion,
    reason: str,
) -> ApplicationFillBlockedField:
    return ApplicationFillBlockedField(
        label=question.question,
        reason=reason,
        required=question.required,
        input_type=question.input_type,
        source=question.evidence,
        confidence=question.confidence,
    )


def _target_from_form_field(
    field: ApplicationFormField,
    *,
    default_reason: str,
) -> FillPlanTargetField:
    return FillPlanTargetField(
        label=field.label,
        name=field.name,
        required=field.required,
        input_type=field.input_type,
        source=field.evidence,
        confidence=field.confidence,
        kind="form_field",
        default_reason=default_reason,
    )


def _target_from_screening_question(
    question: ApplicationScreeningQuestion,
    *,
    default_reason: str,
) -> FillPlanTargetField:
    return FillPlanTargetField(
        label=question.question,
        required=question.required,
        input_type=question.input_type,
        source=question.evidence,
        confidence=question.confidence,
        kind="screening_question",
        default_reason=default_reason,
    )


def _blocked_from_target_field(
    target: FillPlanTargetField,
    reason: str,
) -> ApplicationFillBlockedField:
    return ApplicationFillBlockedField(
        label=target.label,
        name=target.name,
        reason=reason,
        required=target.required,
        input_type=target.input_type,
        source=target.source,
        confidence=target.confidence,
    )


def _candidate_evidence(candidate_profile: CandidateProfile) -> dict[str, object]:
    profile = candidate_profile.candidate_profile
    extracted = profile.cv_extracted
    return {
        "identity": extracted.identity.model_dump(mode="json"),
        "candidate_preferences": profile.candidate_preferences.model_dump(mode="json"),
        "work_experience": extracted.work_experience,
        "education": extracted.education,
        "skills": extracted.skills,
        "languages": extracted.languages,
        "certifications": extracted.certifications,
        "projects": extracted.projects,
        "references": extracted.references,
    }


def _package_form_answers(package: ApplicationPackage) -> list[dict[str, object]]:
    return [
        {
            "label": artifact.label,
            "content": artifact.content,
            "source_prompt": artifact.source_prompt,
            "source_requirement": artifact.source_requirement,
        }
        for artifact in package.artifacts
        if artifact.type == "form_answer" and artifact.content.strip()
    ]


def _to_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)


def _split_full_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _city_from_location(location: str) -> str:
    return location.split(",", maxsplit=1)[0].strip()


def _country_from_location(location: str) -> str:
    normalized = location.casefold()
    if "germany" in normalized or "deutschland" in normalized or "berlin" in normalized:
        return "Deutschland"
    return ""


def _field_key(value: str) -> str:
    normalized = value.casefold()
    normalized = normalized.replace("*", "")
    normalized = re.sub(r"[^a-z0-9äöüß@.+ -]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _dedupe_field_values(
    field_values: list[ApplicationFillFieldValue],
) -> list[ApplicationFillFieldValue]:
    seen: set[str] = set()
    deduped: list[ApplicationFillFieldValue] = []
    for field in field_values:
        key = _field_key(field.label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(field)
    return deduped


def _dedupe_blocked_fields(
    blocked_fields: list[ApplicationFillBlockedField],
) -> list[ApplicationFillBlockedField]:
    seen: set[str] = set()
    deduped: list[ApplicationFillBlockedField] = []
    for field in blocked_fields:
        key = _field_key(field.label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(field)
    return deduped
