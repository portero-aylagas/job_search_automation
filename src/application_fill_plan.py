"""Generate, edit, and persist reviewed application fill plans."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from src import llm_client
from src.application_package_quality import is_sensitive_or_user_decision_field
from src.paths import application_fill_plan_paths, runtime_application_fill_plan_path
from src.prompt_templates import get_prompt
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillEvidenceSource,
    ApplicationFillEvidenceStatus,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationPageControl,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
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

FillPlanEvidenceItem = TypeVar(
    "FillPlanEvidenceItem",
    ApplicationFillFieldValue,
    ApplicationFillUploadFile,
    ApplicationFillBlockedField,
    ApplicationFillNeedsAnswerField,
)


@dataclass(frozen=True)
class FillPlanTargetField:
    """Application field that still needs a safe value mapping."""

    label: str
    name: str = ""
    required: bool = False
    input_type: str = ""
    options: tuple[str, ...] = ()
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    kind: str = "field"
    default_reason: str = "No safe candidate or reviewed package value is available."


@dataclass(frozen=True)
class FillPlanEvidence:
    """Literal snapshot evidence attached to a fill-plan item."""

    literal_evidence: list[str]
    evidence_source: ApplicationFillEvidenceSource
    evidence_status: ApplicationFillEvidenceStatus


class ApplicationFieldMappingSuggestion(BaseModel):
    """Suggested value for one unresolved application field."""

    label: str
    action: Literal["fill", "skip_duplicate", "block"] = "fill"
    value: str = ""
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    reason: str = ""


class LLMApplicationFieldMappingResponse(BaseModel):
    """Structured response for semantic application field mapping."""

    suggestions: list[ApplicationFieldMappingSuggestion] = []


ApplicationFieldMapper = Callable[
    [
        CandidateProfile,
        ApplicationRequirements,
        ApplicationPackage,
        list[FillPlanTargetField],
        list[ApplicationFillFieldValue],
    ],
    list[ApplicationFieldMappingSuggestion],
]


def generate_application_fill_plan(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    *,
    page_snapshot: ApplicationPageSnapshot | None = None,
    semantic_mapper: ApplicationFieldMapper | None = None,
) -> ApplicationFillPlan:
    """Create a conservative draft fill plan from reviewed application data."""

    field_values: list[ApplicationFillFieldValue] = []
    blocked_fields: list[ApplicationFillBlockedField] = []
    needs_answer_fields: list[ApplicationFillNeedsAnswerField] = []
    unresolved_fields: list[FillPlanTargetField] = []
    used_fields: set[str] = set()

    for field in [*requirements.profile_fields, *requirements.custom_form_fields]:
        key = _field_key(field.label or field.name)
        dedupe_key = _field_dedupe_key(field.label, field.name)
        if dedupe_key in used_fields:
            continue
        if _should_block_field(key):
            blocked_fields.append(
                _blocked_from_form_field(
                    field,
                    "Field requires user review.",
                    page_snapshot=page_snapshot,
                )
            )
            continue

        candidate_value = _candidate_value_for_field(candidate_profile, field)
        if candidate_value:
            field_values.append(
                _attach_fill_plan_evidence(
                    ApplicationFillFieldValue(
                        label=field.label,
                        name=field.name,
                        value=candidate_value,
                        required=field.required,
                        input_type=field.input_type,
                        options=list(field.options),
                        source=_candidate_source_for_field(field),
                        confidence="high",
                    ),
                    page_snapshot,
                    _terms_from_form_field(field),
                )
            )
            used_fields.add(dedupe_key)
            continue

        package_value = _package_answer_for_label(package, field.label)
        if package_value:
            field_values.append(
                _attach_fill_plan_evidence(
                    ApplicationFillFieldValue(
                        label=field.label,
                        name=field.name,
                        value=package_value,
                        required=field.required,
                        input_type=field.input_type,
                        options=list(field.options),
                        source="application_package.form_answer",
                        confidence="medium",
                    ),
                    page_snapshot,
                    _terms_from_form_field(field),
                )
            )
            used_fields.add(dedupe_key)
            continue

        reason = "No safe candidate or reviewed package value is available."
        unresolved_fields.append(_target_from_form_field(field, default_reason=reason))

    for question in requirements.screening_questions:
        key = _field_key(question.question)
        dedupe_key = _field_dedupe_key(question.question)
        if dedupe_key in used_fields:
            continue
        if _should_block_field(key):
            blocked_fields.append(
                _blocked_from_screening_question(
                    question,
                    "Field requires user review.",
                    page_snapshot=page_snapshot,
                )
            )
            continue

        package_value = _package_answer_for_label(package, question.question)
        if package_value:
            field_values.append(
                _attach_fill_plan_evidence(
                    ApplicationFillFieldValue(
                        label=question.question,
                        value=package_value,
                        required=question.required,
                        input_type=question.input_type,
                        options=[],
                        source="application_package.form_answer",
                        confidence="medium",
                    ),
                    page_snapshot,
                    _terms_from_screening_question(question),
                )
            )
            used_fields.add(dedupe_key)
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
        needs_answer_fields,
        page_snapshot,
    )

    for requirement in [
        *requirements.consent_requirements,
        *requirements.privacy_login_ats_gates,
    ]:
        blocked_fields.append(
            _attach_fill_plan_evidence(
                ApplicationFillBlockedField(
                    label=requirement.label,
                    reason="Consent, privacy, login, or ATS gate requires user review.",
                    required=requirement.required,
                    input_type="checkbox",
                    options=["true", "false"],
                    source=requirement.evidence,
                    confidence=requirement.confidence,
                ),
                page_snapshot,
                _terms_from_requirement_finding(requirement),
            )
        )

    return ApplicationFillPlan(
        job_id=requirements.job_id,
        apply_url=requirements.apply_url,
        review_status="draft",
        field_values=_dedupe_field_values(field_values),
        upload_files=_build_upload_files(candidate_profile, requirements, page_snapshot),
        needs_answer_fields=_dedupe_needs_answer_fields(needs_answer_fields),
        blocked_fields=_dedupe_blocked_fields(blocked_fields),
        submit_guard_labels=DEFAULT_SUBMIT_GUARD_LABELS,
    )


def apply_fill_plan_edits(
    fill_plan: ApplicationFillPlan,
    values_by_key: dict[str, str],
    *,
    upload_paths_by_key: dict[str, str] | None = None,
    needs_answer_values_by_key: dict[str, str] | None = None,
    blocked_values_by_key: dict[str, str] | None = None,
) -> ApplicationFillPlan:
    """Return a fill plan with reviewer-edited field values."""

    edited = fill_plan.model_copy(deep=True)
    kept_fields: list[ApplicationFillFieldValue] = []
    for index, field in enumerate(edited.field_values):
        edit_key = fill_plan_field_edit_key(field, index)
        if edit_key in values_by_key:
            updated_value = values_by_key[edit_key].strip()
            if updated_value != field.value:
                field.value = updated_value
                field.source = "manual_review"
        kept_fields.append(field)

    kept_uploads: list[ApplicationFillUploadFile] = []
    for index, upload in enumerate(edited.upload_files):
        edit_key = fill_plan_upload_edit_key(upload, index)
        if upload_paths_by_key is not None and edit_key in upload_paths_by_key:
            updated_path = upload_paths_by_key[edit_key].strip()
            if updated_path != upload.file_path:
                upload.file_path = updated_path
                upload.source = "manual_review"
        kept_uploads.append(upload)
    edited.upload_files = kept_uploads

    unresolved_needs_answer_fields: list[ApplicationFillNeedsAnswerField] = []
    answer_values = needs_answer_values_by_key or {}
    for index, field in enumerate(edited.needs_answer_fields):
        edit_key = fill_plan_needs_answer_edit_key(field, index)
        if edit_key in answer_values:
            updated_value = answer_values[edit_key].strip()
            kept_fields.append(_field_value_from_needs_answer_field(field, updated_value))
            continue

        unresolved_needs_answer_fields.append(field)

    unresolved_blocked_fields: list[ApplicationFillBlockedField] = []
    blocked_values = blocked_values_by_key or {}
    for index, field in enumerate(edited.blocked_fields):
        edit_key = fill_plan_blocked_field_edit_key(field, index)
        if edit_key in blocked_values:
            updated_value = blocked_values[edit_key].strip()
            kept_fields.append(_field_value_from_blocked_field(field, updated_value))
            continue

        unresolved_blocked_fields.append(field)

    edited.field_values = _dedupe_field_values(kept_fields)
    edited.needs_answer_fields = _dedupe_needs_answer_fields(
        unresolved_needs_answer_fields
    )
    edited.blocked_fields = _dedupe_blocked_fields(unresolved_blocked_fields)
    edited.review_status = "draft"
    return edited


def fill_plan_field_edit_key(field: ApplicationFillFieldValue, index: int) -> str:
    """Return a stable edit key for one fill-plan field row."""

    identity = field.name.strip() or field.label.strip() or "field"
    return f"field:{index}:{_field_key(identity)}"


def fill_plan_upload_edit_key(upload: ApplicationFillUploadFile, index: int) -> str:
    """Return a stable edit key for one fill-plan upload row."""

    identity = upload.label.strip() or upload.document_type.strip() or "upload"
    return f"upload:{index}:{_field_key(identity)}"


def fill_plan_needs_answer_edit_key(
    field: ApplicationFillNeedsAnswerField,
    index: int,
) -> str:
    """Return a stable edit key for one needs-answer fill-plan row."""

    identity = field.name.strip() or field.label.strip() or "field"
    return f"needs-answer:{index}:{_field_key(identity)}"


def fill_plan_blocked_field_edit_key(
    field: ApplicationFillBlockedField,
    index: int,
) -> str:
    """Return a stable edit key for one blocked fill-plan row."""

    identity = field.name.strip() or field.label.strip() or "field"
    return f"blocked:{index}:{_field_key(identity)}"


def get_application_fill_plan_review_blockers(fill_plan: ApplicationFillPlan) -> list[str]:
    """Return blockers that prevent marking an application fill plan reviewed."""

    blockers: list[str] = []
    if fill_plan.needs_answer_fields:
        blockers.append("Save reviewed values for all fields needing answers.")
    if fill_plan.blocked_fields:
        blockers.append("Save reviewed values for all previously blocked fields.")

    required_blank_fields = [
        field.label
        for field in fill_plan.field_values
        if field.required and not field.value.strip()
    ]
    if required_blank_fields:
        blockers.append(
            "Provide values for required fields: "
            + ", ".join(required_blank_fields)
            + "."
        )

    required_blank_uploads = [
        upload.label
        for upload in fill_plan.upload_files
        if upload.required and not upload.file_path.strip()
    ]
    if required_blank_uploads:
        blockers.append(
            "Provide file paths for required uploads: "
            + ", ".join(required_blank_uploads)
            + "."
        )

    return blockers


def mark_application_fill_plan_reviewed(fill_plan: ApplicationFillPlan) -> ApplicationFillPlan:
    """Return a fill plan marked as reviewed."""

    blockers = get_application_fill_plan_review_blockers(fill_plan)
    if blockers:
        raise ValueError(" ".join(blockers))

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
    resolved_fields: list[ApplicationFillFieldValue],
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
                    resolved_fields_json=_to_json(
                        [field.model_dump(mode="json") for field in resolved_fields]
                    ),
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
    needs_answer_fields: list[ApplicationFillNeedsAnswerField],
    page_snapshot: ApplicationPageSnapshot | None,
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
                field_values,
            )
        }

    for target in unresolved_fields:
        suggestion = suggestions_by_label.get(_field_key(target.label))
        if suggestion is not None and suggestion.action == "skip_duplicate":
            reason = suggestion.reason.strip() or (
                "Potential duplicate of an already resolved field; review manually."
            )
            blocked_fields.append(
                _blocked_from_target_field(
                    target,
                    reason,
                    page_snapshot=page_snapshot,
                )
            )
            continue

        if suggestion is not None and suggestion.action == "block":
            reason = suggestion.reason.strip() or target.default_reason
            blocked_fields.append(
                _blocked_from_target_field(
                    target,
                    reason,
                    page_snapshot=page_snapshot,
                )
            )
            continue

        if (
            suggestion is not None
            and suggestion.action == "fill"
            and suggestion.value.strip()
        ):
            field_values.append(
                _attach_fill_plan_evidence(
                    ApplicationFillFieldValue(
                        label=target.label,
                        name=target.name,
                        value=suggestion.value.strip(),
                        required=target.required,
                        input_type=target.input_type,
                        options=list(target.options),
                        source=suggestion.source or "application_field_mapping",
                        confidence=suggestion.confidence,
                    ),
                    page_snapshot,
                    _terms_from_target_field(target),
                )
            )
            continue

        reason = target.default_reason
        if suggestion is not None and suggestion.reason.strip():
            reason = suggestion.reason.strip()
        if not target.required:
            blocked_fields.append(
                _blocked_from_target_field(
                    target,
                    f"Optional field left empty because no reviewed value is available. {reason}",
                    page_snapshot=page_snapshot,
                )
            )
            continue
        needs_answer_fields.append(
            _needs_answer_from_target_field(
                target,
                reason,
                page_snapshot=page_snapshot,
            )
        )


def _candidate_value_for_field(
    candidate_profile: CandidateProfile,
    field: ApplicationFormField,
) -> str:
    identity = candidate_profile.candidate_profile.cv_extracted.identity
    first_name = identity.first_name.strip()
    last_name = identity.last_name.strip()
    if not first_name or not last_name:
        split_first, split_last = _split_full_name(identity.full_name)
        first_name = first_name or split_first
        last_name = last_name or split_last
    label = _field_key(field.label or field.name)
    location = identity.location.strip()

    if any(term in label for term in ("anrede", "salutation")):
        return _salutation_from_gender(identity.gender, field.options, label)
    if "gender" in label:
        return identity.gender or ""
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
    if any(term in label for term in ("hausnummer", "street number", "house number")):
        return identity.street_number.strip()
    if any(term in label for term in ("straße", "strasse", "street", "address", "hausanschrift")):
        if re.search(r"\bnr\b", label) or "house number" in label:
            return " ".join(
                item
                for item in (identity.street_address.strip(), identity.street_number.strip())
                if item
            )
        return identity.street_address.strip()
    if (
        ("land" in label and "wohn" in label)
        or "country of residence" in label
        or label == "country"
    ):
        return identity.country.strip() or _country_from_location(location)
    if "nationality" in label or "staatsangehörigkeit" in label:
        return identity.nationality.strip()
    if "linkedin" in label:
        return identity.linkedin_url.strip()
    if "github" in label:
        return identity.github_url.strip()
    if "portfolio" in label or "website" in label:
        return identity.portfolio_url.strip()
    return ""


def _candidate_source_for_field(field: ApplicationFormField) -> str:
    label = _field_key(field.label or field.name)
    if any(term in label for term in ("anrede", "salutation")) or "gender" in label:
        return "candidate_profile.cv_extracted.identity.gender"
    if any(term in label for term in ("vorname", "first name", "given name")):
        return "candidate_profile.cv_extracted.identity.first_name"
    if any(term in label for term in ("nachname", "last name", "surname", "family name")):
        return "candidate_profile.cv_extracted.identity.last_name"
    if "mail" in label:
        return "candidate_profile.cv_extracted.identity.email"
    if any(term in label for term in ("telefon", "phone", "mobile", "handy")):
        return "candidate_profile.cv_extracted.identity.phone"
    if "postleitzahl" in label or "postal" in label or "zip" in label:
        return "candidate_profile.cv_extracted.identity.postal_code"
    if any(term in label for term in ("hausnummer", "street number", "house number")):
        return "candidate_profile.cv_extracted.identity.street_number"
    if any(term in label for term in ("straße", "strasse", "street", "address", "hausanschrift")):
        return "candidate_profile.cv_extracted.identity.street_address"
    if label in {"ort", "city", "wohnort"}:
        return "candidate_profile.cv_extracted.identity.city"
    if (
        ("land" in label and "wohn" in label)
        or "country of residence" in label
        or label == "country"
    ):
        return "candidate_profile.cv_extracted.identity.country"
    if "nationality" in label or "staatsangehörigkeit" in label:
        return "candidate_profile.cv_extracted.identity.nationality"
    if "linkedin" in label:
        return "candidate_profile.cv_extracted.identity.linkedin_url"
    if "github" in label:
        return "candidate_profile.cv_extracted.identity.github_url"
    if "portfolio" in label or "website" in label:
        return "candidate_profile.cv_extracted.identity.portfolio_url"
    return "candidate_profile.cv_extracted.identity.location"


def _salutation_from_gender(gender: str | None, options: list[str], label: str) -> str:
    """Return the best supported salutation for a reviewed gender value."""

    if gender == "Female":
        return _matching_option(options, ("frau", "ms", "ms.", "mrs", "mrs.")) or (
            "Frau" if "anrede" in label else "Ms"
        )
    if gender == "Male":
        return _matching_option(options, ("herr", "mr", "mr.")) or (
            "Herr" if "anrede" in label else "Mr"
        )
    if gender == "Diverse":
        return _matching_option(options, ("divers", "diverse", "mx", "mx.")) or (
            "Divers" if "anrede" in label else "Mx"
        )
    return ""


def _matching_option(options: list[str], accepted_values: tuple[str, ...]) -> str:
    accepted = {value.lower() for value in accepted_values}
    for option in options:
        if option.strip().lower() in accepted:
            return option
    return ""


def _build_upload_files(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    page_snapshot: ApplicationPageSnapshot | None,
) -> list[ApplicationFillUploadFile]:
    cv_path = candidate_profile.candidate_profile.source_documents.cv.file_path.strip()
    if not cv_path:
        return []

    required = any(item.required for item in requirements.required_documents)
    label = "CV / Resume"
    matched_requirement: ApplicationRequirementFinding | None = None
    for item in [*requirements.required_documents, *requirements.upload_expectations]:
        item_text = _field_key(" ".join([item.label, item.evidence, *item.constraints]))
        upload_terms = ("cv", "resume", "lebenslauf", "bewerbungsunterlagen")
        if any(term in item_text for term in upload_terms):
            label = item.label
            required = required or item.required
            matched_requirement = item
            break

    evidence_terms = (
        _terms_from_requirement_finding(matched_requirement)
        if matched_requirement is not None
        else ["CV / Resume"]
    )
    return [
        _attach_fill_plan_evidence(
            ApplicationFillUploadFile(
                label=label,
                file_path=cv_path,
                document_type="cv",
                required=required,
                source="candidate_profile.source_documents.cv.file_path",
                confidence="high",
            ),
            page_snapshot,
            evidence_terms,
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
    *,
    page_snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillBlockedField:
    return _attach_fill_plan_evidence(
        ApplicationFillBlockedField(
            label=field.label,
            name=field.name,
            reason=reason,
            required=field.required,
            input_type=field.input_type,
            options=list(field.options),
            source=field.evidence,
            confidence=field.confidence,
        ),
        page_snapshot,
        _terms_from_form_field(field),
    )


def _blocked_from_screening_question(
    question: ApplicationScreeningQuestion,
    reason: str,
    *,
    page_snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillBlockedField:
    return _attach_fill_plan_evidence(
        ApplicationFillBlockedField(
            label=question.question,
            reason=reason,
            required=question.required,
            input_type=question.input_type,
            options=[],
            source=question.evidence,
            confidence=question.confidence,
        ),
        page_snapshot,
        _terms_from_screening_question(question),
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
        options=tuple(field.options),
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
        options=(),
        source=question.evidence,
        confidence=question.confidence,
        kind="screening_question",
        default_reason=default_reason,
    )


def _blocked_from_target_field(
    target: FillPlanTargetField,
    reason: str,
    *,
    page_snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillBlockedField:
    return _attach_fill_plan_evidence(
        ApplicationFillBlockedField(
            label=target.label,
            name=target.name,
            reason=reason,
            required=target.required,
            input_type=target.input_type,
            options=list(target.options),
            source=target.source,
            confidence=target.confidence,
        ),
        page_snapshot,
        _terms_from_target_field(target),
    )


def _needs_answer_from_target_field(
    target: FillPlanTargetField,
    reason: str,
    *,
    page_snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillNeedsAnswerField:
    return _attach_fill_plan_evidence(
        ApplicationFillNeedsAnswerField(
            label=target.label,
            name=target.name,
            reason=reason,
            required=target.required,
            input_type=target.input_type,
            options=list(target.options),
            source=target.source,
            confidence=target.confidence,
        ),
        page_snapshot,
        _terms_from_target_field(target),
    )


def _field_value_from_needs_answer_field(
    field: ApplicationFillNeedsAnswerField,
    value: str,
) -> ApplicationFillFieldValue:
    return ApplicationFillFieldValue(
        label=field.label,
        name=field.name,
        value=value,
        required=field.required,
        input_type=field.input_type,
        options=list(field.options),
        source="manual_review",
        confidence="high",
        literal_evidence=list(field.literal_evidence),
        evidence_source=field.evidence_source,
        evidence_status=field.evidence_status,
    )


def _field_value_from_blocked_field(
    field: ApplicationFillBlockedField,
    value: str,
) -> ApplicationFillFieldValue:
    return ApplicationFillFieldValue(
        label=field.label,
        name=field.name,
        value=value,
        required=field.required,
        input_type=field.input_type,
        options=list(field.options),
        source="manual_review",
        confidence="high",
        literal_evidence=list(field.literal_evidence),
        evidence_source=field.evidence_source,
        evidence_status=field.evidence_status,
    )


def _attach_fill_plan_evidence(
    item: FillPlanEvidenceItem,
    page_snapshot: ApplicationPageSnapshot | None,
    terms: list[str],
) -> FillPlanEvidenceItem:
    evidence = _find_fill_plan_evidence(page_snapshot, terms)
    item.literal_evidence = evidence.literal_evidence
    item.evidence_source = evidence.evidence_source
    item.evidence_status = evidence.evidence_status
    return item


def _find_fill_plan_evidence(
    page_snapshot: ApplicationPageSnapshot | None,
    terms: list[str],
) -> FillPlanEvidence:
    if page_snapshot is None:
        return _interpreted_only_evidence()

    evidence_terms = _dedupe_evidence_terms(terms)
    if not evidence_terms:
        return _interpreted_only_evidence()

    for matcher in (
        _match_control_evidence,
        _match_form_label_evidence,
        _match_evidence_match_evidence,
        _match_visible_text_evidence,
        _match_raw_html_evidence,
    ):
        evidence = matcher(page_snapshot, evidence_terms)
        if evidence is not None:
            return evidence

    return _interpreted_only_evidence()


def _interpreted_only_evidence() -> FillPlanEvidence:
    return FillPlanEvidence(
        literal_evidence=[],
        evidence_source="interpreted_only",
        evidence_status="interpreted_only",
    )


def _terms_from_form_field(field: ApplicationFormField) -> list[str]:
    return [field.name, field.label, field.evidence]


def _terms_from_screening_question(question: ApplicationScreeningQuestion) -> list[str]:
    return [question.question, question.evidence]


def _terms_from_requirement_finding(
    requirement: ApplicationRequirementFinding | None,
) -> list[str]:
    if requirement is None:
        return []
    return [requirement.label, requirement.evidence, *requirement.constraints]


def _terms_from_target_field(target: FillPlanTargetField) -> list[str]:
    return [target.name, target.label, target.source]


def _match_control_evidence(
    snapshot: ApplicationPageSnapshot,
    terms: list[str],
) -> FillPlanEvidence | None:
    for term in terms:
        term_key = _field_key(term)
        for control in _snapshot_controls(snapshot):
            candidates = [control.name, control.label, control.evidence]
            if any(_field_key(candidate) == term_key for candidate in candidates):
                snippet = control.label.strip() or control.evidence.strip() or control.name.strip()
                if snippet:
                    return FillPlanEvidence(
                        literal_evidence=[snippet],
                        evidence_source="control_label",
                        evidence_status="literal_verified",
                    )
    return None


def _match_form_label_evidence(
    snapshot: ApplicationPageSnapshot,
    terms: list[str],
) -> FillPlanEvidence | None:
    for term in terms:
        term_key = _field_key(term)
        for form in snapshot.forms:
            for label in form.labels:
                if _field_key(label) == term_key and label.strip():
                    return FillPlanEvidence(
                        literal_evidence=[label.strip()],
                        evidence_source="form_label",
                        evidence_status="literal_verified",
                    )
    return None


def _match_evidence_match_evidence(
    snapshot: ApplicationPageSnapshot,
    terms: list[str],
) -> FillPlanEvidence | None:
    for term in terms:
        term_key = _field_key(term)
        for evidence_match in snapshot.evidence_matches:
            if _field_key(evidence_match) == term_key and evidence_match.strip():
                return FillPlanEvidence(
                    literal_evidence=[evidence_match.strip()],
                    evidence_source="evidence_match",
                    evidence_status="literal_verified",
                )
    return None


def _match_visible_text_evidence(
    snapshot: ApplicationPageSnapshot,
    terms: list[str],
) -> FillPlanEvidence | None:
    return _match_excerpt_evidence(
        snapshot.visible_text_excerpt,
        terms,
        evidence_source="visible_text_excerpt",
    )


def _match_raw_html_evidence(
    snapshot: ApplicationPageSnapshot,
    terms: list[str],
) -> FillPlanEvidence | None:
    return _match_excerpt_evidence(
        snapshot.raw_html_excerpt,
        terms,
        evidence_source="raw_html_excerpt",
    )


def _match_excerpt_evidence(
    excerpt: str,
    terms: list[str],
    *,
    evidence_source: ApplicationFillEvidenceSource,
) -> FillPlanEvidence | None:
    if not excerpt.strip():
        return None

    for term in terms:
        if not _is_conservative_substring_term(term):
            continue
        snippet = _substring_snippet(excerpt, term)
        if snippet:
            return FillPlanEvidence(
                literal_evidence=[snippet],
                evidence_source=evidence_source,
                evidence_status="partial_match",
            )
    return None


def _snapshot_controls(snapshot: ApplicationPageSnapshot) -> list[ApplicationPageControl]:
    controls = list(snapshot.controls)
    for form in snapshot.forms:
        controls.extend(form.controls)
    return controls


def _dedupe_evidence_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for value in values:
        term = value.strip()
        key = _field_key(term)
        if not key or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def _is_conservative_substring_term(term: str) -> bool:
    normalized = _field_key(term)
    alnum_count = sum(1 for char in normalized if char.isalnum())
    return len(normalized) >= 4 and alnum_count >= 4


def _substring_snippet(excerpt: str, term: str) -> str:
    index = excerpt.casefold().find(term.strip().casefold())
    if index < 0:
        return ""

    start = max(0, index - 40)
    end = min(len(excerpt), index + len(term) + 40)
    return re.sub(r"\s+", " ", excerpt[start:end]).strip()


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


def _field_dedupe_key(label: str, name: str = "") -> str:
    normalized_name = _field_key(name)
    if normalized_name:
        return f"name:{normalized_name}"
    return f"label:{_field_key(label)}"


def _field_value_priority(field: ApplicationFillFieldValue) -> tuple[int, int, int, int]:
    source = (field.source or "").casefold()
    source_priority = 0
    if source == "manual_review":
        source_priority = 4
    elif source == "application_package.form_answer":
        source_priority = 3
    elif source.startswith("candidate_profile."):
        source_priority = 2
    elif source == "application_field_mapping":
        source_priority = 1

    confidence_priority = {"low": 0, "medium": 1, "high": 2}.get(field.confidence, 0)
    label_specificity = len(_field_key(field.label).split())
    return (
        source_priority,
        int(field.required),
        confidence_priority,
        label_specificity,
    )


def _dedupe_field_values(
    field_values: list[ApplicationFillFieldValue],
) -> list[ApplicationFillFieldValue]:
    deduped_by_key: dict[str, ApplicationFillFieldValue] = {}
    ordered_keys: list[str] = []
    for field in field_values:
        key = _field_dedupe_key(field.label, field.name)
        existing = deduped_by_key.get(key)
        if existing is None:
            deduped_by_key[key] = field
            ordered_keys.append(key)
            continue
        if _field_value_priority(field) > _field_value_priority(existing):
            deduped_by_key[key] = field
    return [deduped_by_key[key] for key in ordered_keys]


def _dedupe_blocked_fields(
    blocked_fields: list[ApplicationFillBlockedField],
) -> list[ApplicationFillBlockedField]:
    seen: set[str] = set()
    deduped: list[ApplicationFillBlockedField] = []
    for field in blocked_fields:
        key = _field_dedupe_key(field.label, field.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(field)
    return deduped


def _dedupe_needs_answer_fields(
    needs_answer_fields: list[ApplicationFillNeedsAnswerField],
) -> list[ApplicationFillNeedsAnswerField]:
    seen: set[str] = set()
    deduped: list[ApplicationFillNeedsAnswerField] = []
    for field in needs_answer_fields:
        key = _field_dedupe_key(field.label, field.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(field)
    return deduped
