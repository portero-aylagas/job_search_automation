"""Candidate profile validation and merge helpers."""

from __future__ import annotations

import re
from pathlib import Path

from src.schemas import (
    CandidateCVExtracted,
    CandidateOptionalDocument,
    CandidateProfile,
    CandidateSupplementalExtracted,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGIT_PATTERN = re.compile(r"\d")
UPLOAD_TIMESTAMP_PREFIX_PATTERN = re.compile(r"^\d{14}-(?=.)")


def validate_candidate_profile(candidate_profile: CandidateProfile) -> list[str]:
    """Return known-job application blockers for a candidate profile.

    Args:
        candidate_profile: Candidate profile draft or saved profile to validate.
    """

    return validate_known_job_candidate_profile(candidate_profile)


def validate_known_job_candidate_profile(candidate_profile: CandidateProfile) -> list[str]:
    """Return profile fields required for applying to a known saved job.

    Job-search preferences are optional metadata in the known-job workflow. They
    are validated only for internal consistency when present.
    """

    profile = candidate_profile.candidate_profile
    errors: list[str] = []

    if not profile.source_documents.cv.file_path.strip():
        errors.append("Upload CV")
    identity = profile.cv_extracted.identity
    if not identity.first_name.strip():
        errors.append("First name")
    if not identity.last_name.strip():
        errors.append("Surname")
    if not identity.email.strip():
        errors.append("Email")
    elif not is_valid_email(identity.email):
        errors.append("Email must be valid")
    if not identity.phone.strip():
        errors.append("Phone")
    elif len(PHONE_DIGIT_PATTERN.findall(identity.phone)) < 7:
        errors.append("Phone must be valid")
    if identity.gender is None:
        errors.append("Gender")
    if not identity.street_address.strip():
        errors.append("Street")
    if not identity.street_number.strip():
        errors.append("Street number")
    if not identity.city.strip():
        errors.append("City")
    if not identity.postal_code.strip():
        errors.append("Postal code")
    if not identity.country.strip():
        errors.append("Country of residence")
    if not identity.nationality.strip():
        errors.append("Nationality")
    if (
        profile.candidate_preferences.salary_min_eur is not None
        and profile.candidate_preferences.salary_max_eur is not None
        and (
            profile.candidate_preferences.salary_max_eur
            < profile.candidate_preferences.salary_min_eur
        )
    ):
        errors.append("Salary max must be >= Salary min")

    return errors


def validate_candidate_discovery_preferences(
    candidate_profile: CandidateProfile,
) -> list[str]:
    """Return optional future job-discovery preference validation errors."""

    preferences = candidate_profile.candidate_profile.candidate_preferences
    errors: list[str] = []
    if not preferences.target_roles:
        errors.append("Target roles")
    if not preferences.target_locations:
        errors.append("Target locations")
    if not preferences.remote_preference:
        errors.append("Remote preference")
    if not preferences.employment_type:
        errors.append("Employment type")
    if not preferences.seniority_level:
        errors.append("Career level")
    if not preferences.availability.strip():
        errors.append("Availability")
    if preferences.salary_min_eur is None:
        errors.append("Salary min")
    if preferences.salary_max_eur is None:
        errors.append("Salary max")
    if (
        preferences.salary_min_eur is not None
        and preferences.salary_max_eur is not None
        and preferences.salary_max_eur < preferences.salary_min_eur
    ):
        errors.append("Salary max must be >= Salary min")
    if not str(preferences.work_authorization).strip():
        errors.append("Work authorization")
    return errors


def is_valid_email(value: str) -> bool:
    """Return whether an email value is non-empty and syntactically plausible."""

    return EMAIL_PATTERN.fullmatch(value.strip()) is not None


def normalize_candidate_profile_documents(
    candidate_profile: CandidateProfile,
) -> CandidateProfile:
    """Return a copy with repeated optional document uploads collapsed.

    Optional document uploads are stored with timestamped runtime paths. When the
    same category and original filename is uploaded again, the newest metadata
    entry should replace the older one while distinct filenames remain available.
    """

    normalized_profile = candidate_profile.model_copy(deep=True)
    source_documents = normalized_profile.candidate_profile.source_documents
    source_documents.optional_documents = dedupe_optional_documents(
        source_documents.optional_documents
    )
    return normalized_profile


def dedupe_optional_documents(
    documents: list[CandidateOptionalDocument],
) -> list[CandidateOptionalDocument]:
    """Return optional documents deduped by category and original filename."""

    documents_by_key: dict[tuple[str, str], CandidateOptionalDocument] = {}
    ordered_keys: list[tuple[str, str]] = []
    for document in documents:
        key = _optional_document_dedupe_key(document)
        if key not in documents_by_key:
            ordered_keys.append(key)
        documents_by_key[key] = document
    return [documents_by_key[key] for key in ordered_keys]


def candidate_optional_document_display_name(
    document: CandidateOptionalDocument,
) -> str:
    """Return the original optional-document filename for labels and dedupe."""

    file_name = document.file_name.strip()
    if not file_name:
        file_name = Path(document.file_path).name.strip()
    return UPLOAD_TIMESTAMP_PREFIX_PATTERN.sub("", file_name)


def _optional_document_dedupe_key(
    document: CandidateOptionalDocument,
) -> tuple[str, str]:
    document_type = document.document_type.strip().casefold() or "other"
    file_name = candidate_optional_document_display_name(document).strip().casefold()
    if not file_name:
        file_name = document.file_path.strip().casefold()
    return (document_type, file_name)


def merge_supplemental_extracted_data(
    target: CandidateCVExtracted,
    supplemental: CandidateSupplementalExtracted,
) -> None:
    """Merge supplemental document evidence into extracted CV data in place.

    Args:
        target: Existing CV-derived profile data that will be mutated.
        supplemental: Additional evidence extracted from optional documents.
    """

    target.work_experience = _merge_unique_items(
        target.work_experience,
        supplemental.work_experience,
    )
    target.education = _merge_unique_items(target.education, supplemental.education)
    target.skills = _merge_unique_items(target.skills, supplemental.skills)
    target.languages = _merge_unique_items(target.languages, supplemental.languages)
    target.certifications = _merge_unique_items(
        target.certifications,
        supplemental.certifications,
    )
    target.projects = _merge_unique_items(target.projects, supplemental.projects)
    target.references = _merge_unique_items(target.references, supplemental.references)


def _merge_unique_items(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    seen = {item.casefold() for item in existing}
    for item in incoming:
        normalized = item.strip()
        if not normalized or normalized.casefold() in seen:
            continue
        merged.append(normalized)
        seen.add(normalized.casefold())
    return merged
