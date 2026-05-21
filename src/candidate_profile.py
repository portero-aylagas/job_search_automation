"""Candidate profile validation and merge helpers."""

from __future__ import annotations

import re

from src.schemas import (
    CandidateCVExtracted,
    CandidateProfile,
    CandidateSupplementalExtracted,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGIT_PATTERN = re.compile(r"\d")


def validate_candidate_profile(candidate_profile: CandidateProfile) -> list[str]:
    """Return user-facing labels for missing or inconsistent profile fields.

    Args:
        candidate_profile: Candidate profile draft or saved profile to validate.
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
    if not profile.candidate_preferences.target_roles:
        errors.append("Target roles")
    if not profile.candidate_preferences.target_locations:
        errors.append("Target locations")
    if not profile.candidate_preferences.remote_preference:
        errors.append("Remote preference")
    if not profile.candidate_preferences.employment_type:
        errors.append("Employment type")
    if not profile.candidate_preferences.seniority_level:
        errors.append("Career level")
    if not profile.candidate_preferences.availability.strip():
        errors.append("Availability")
    if profile.candidate_preferences.salary_min_eur is None:
        errors.append("Salary min")
    if profile.candidate_preferences.salary_max_eur is None:
        errors.append("Salary max")
    if (
        profile.candidate_preferences.salary_min_eur is not None
        and profile.candidate_preferences.salary_max_eur is not None
        and (
            profile.candidate_preferences.salary_max_eur
            < profile.candidate_preferences.salary_min_eur
        )
    ):
        errors.append("Salary max must be >= Salary min")
    if not str(profile.candidate_preferences.work_authorization).strip():
        errors.append("Work authorization")

    return errors


def is_valid_email(value: str) -> bool:
    """Return whether an email value is non-empty and syntactically plausible."""

    return EMAIL_PATTERN.fullmatch(value.strip()) is not None


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
