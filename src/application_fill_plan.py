"""Generate, edit, and persist reviewed application fill plans."""

from __future__ import annotations

import re
from pathlib import Path

from src.application_package_quality import is_sensitive_or_user_decision_field
from src.paths import application_fill_plan_paths, runtime_application_fill_plan_path
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


def generate_application_fill_plan(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
) -> ApplicationFillPlan:
    """Create a conservative draft fill plan from reviewed application data."""

    field_values: list[ApplicationFillFieldValue] = []
    blocked_fields: list[ApplicationFillBlockedField] = []
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
        blocked_fields.append(_blocked_from_form_field(field, reason))

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
            blocked_fields.append(
                _blocked_from_screening_question(
                    question,
                    "No reviewed package answer is available.",
                )
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


def _candidate_value_for_field(
    candidate_profile: CandidateProfile,
    field: ApplicationFormField,
) -> str:
    identity = candidate_profile.candidate_profile.cv_extracted.identity
    first_name, last_name = _split_full_name(identity.full_name)
    label = _field_key(field.label or field.name)
    location = identity.location.strip()

    if any(term in label for term in ("vorname", "first name", "given name")):
        return first_name
    if any(term in label for term in ("nachname", "last name", "surname", "family name")):
        return last_name
    if any(term in label for term in ("e-mail", "email", "mail adresse", "e-mail-adresse")):
        return identity.email.strip()
    if any(term in label for term in ("telefon", "phone", "mobile", "handy")):
        return identity.phone.strip()
    if label in {"ort", "city", "wohnort"}:
        return _city_from_location(location)
    if "postleitzahl" in label or "postal" in label or "zip" in label:
        return ""
    if "land" in label and "wohn" in label:
        return _country_from_location(location)
    if "linkedin" in label:
        return identity.linkedin_url.strip()
    if "github" in label:
        return identity.github_url.strip()
    if "portfolio" in label or "website" in label:
        return identity.portfolio_url.strip()
    return ""


def _candidate_source_for_field(field: ApplicationFormField) -> str:
    label = _field_key(field.label or field.name)
    if any(term in label for term in ("vorname", "first name", "nachname", "last name")):
        return "candidate_profile.cv_extracted.identity.full_name"
    if "mail" in label:
        return "candidate_profile.cv_extracted.identity.email"
    if any(term in label for term in ("telefon", "phone", "mobile", "handy")):
        return "candidate_profile.cv_extracted.identity.phone"
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
