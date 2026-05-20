from __future__ import annotations

from src.schemas import (
    CandidateCVExtracted,
    CandidateProfile,
    CandidateSupplementalExtracted,
)


def validate_candidate_profile(candidate_profile: CandidateProfile) -> list[str]:
    profile = candidate_profile.candidate_profile
    errors: list[str] = []

    if not profile.source_documents.cv.file_path.strip():
        errors.append("Upload CV")
    if not profile.cv_extracted.identity.full_name.strip():
        errors.append("Full name")
    if not profile.cv_extracted.identity.email.strip():
        errors.append("Email")
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


def merge_supplemental_extracted_data(
    target: CandidateCVExtracted,
    supplemental: CandidateSupplementalExtracted,
) -> None:
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
