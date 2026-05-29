"""Deterministic candidate/job match analysis and tracker updates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.paths import (
    match_analysis_paths,
    runtime_jobs_index_path,
    runtime_match_analysis_path,
    runtime_tracker_path,
)
from src.schemas import (
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    MatchAnalysis,
    MatchScoreComponents,
    TrackerRecord,
)
from src.storage import load_model, save_model

ROLE_WEIGHT = 30.0
SKILL_WEIGHT = 35.0
LOCATION_WEIGHT = 20.0
CONSTRAINT_WEIGHT = 10.0
COMPLETENESS_WEIGHT = 5.0


def analyze_match(
    candidate_profile: CandidateProfile,
    job: JobListing,
    experience_units: list[ExperienceUnit] | None = None,
) -> MatchAnalysis:
    """Build a deterministic draft match analysis for a candidate and job."""

    units = experience_units or []
    matched_skills, missing_skills = match_candidate_skills(candidate_profile, job)
    role_score = _role_match_ratio(candidate_profile, job) * ROLE_WEIGHT
    skill_score = _skill_match_ratio(matched_skills, missing_skills, job) * SKILL_WEIGHT
    location_score = _location_match_ratio(candidate_profile, job) * LOCATION_WEIGHT
    constraint_score = _constraint_match_ratio(candidate_profile, job) * CONSTRAINT_WEIGHT
    completeness_score = _completeness_ratio(candidate_profile, job) * COMPLETENESS_WEIGHT
    components = MatchScoreComponents(
        role_match=round(role_score, 2),
        skill_match=round(skill_score, 2),
        location_match=round(location_score, 2),
        constraint_match=round(constraint_score, 2),
        completeness=round(completeness_score, 2),
    )
    score = round(
        components.role_match
        + components.skill_match
        + components.location_match
        + components.constraint_match
        + components.completeness,
        2,
    )
    relevant_evidence, strong_unit_ids = _relevant_experience_evidence(
        units,
        matched_skills,
        job,
    )
    weak_points = _weak_points(candidate_profile, job, missing_skills)

    return MatchAnalysis(
        job_id=job.id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        match_score=score,
        score_components=components,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        relevant_evidence=relevant_evidence,
        strong_experience_units=strong_unit_ids,
        weak_points=weak_points,
        positioning=_positioning_summary(candidate_profile, job, matched_skills, weak_points),
        strategy=_application_strategy(job, matched_skills, missing_skills, weak_points),
        blockers=_analysis_blockers(candidate_profile, job),
        source_fingerprints=build_match_analysis_fingerprints(
            candidate_profile,
            job,
            units,
        ),
        review_status="draft",
    )


def match_candidate_skills(
    candidate_profile: CandidateProfile,
    job: JobListing,
) -> tuple[list[str], list[str]]:
    """Return matched and missing job skills using deterministic text overlap."""

    candidate_skills = _candidate_skills(candidate_profile)
    candidate_skill_keys = {_skill_key(skill): skill for skill in candidate_skills}
    candidate_text = _candidate_evidence_text(candidate_profile, candidate_skills)
    job_skills = _job_skill_requirements(job)
    matched: list[str] = []
    missing: list[str] = []

    for job_skill in job_skills:
        job_skill_key = _skill_key(job_skill)
        direct_match = job_skill_key in candidate_skill_keys
        text_match = _contains_phrase(candidate_text, job_skill)
        if direct_match or text_match:
            matched.append(_display_skill(candidate_skill_keys.get(job_skill_key, job_skill)))
        else:
            missing.append(_display_skill(job_skill))

    return _dedupe_text(matched), _dedupe_text(missing)


def save_match_analysis(base_dir: Path | str, analysis: MatchAnalysis) -> Path:
    """Persist match analysis JSON for one job workspace."""

    target = runtime_match_analysis_path(base_dir, analysis.job_id)
    save_model(target, analysis)
    return target


def load_match_analysis(base_dir: Path | str, job_id: str) -> MatchAnalysis | None:
    """Load match analysis from runtime data or checked-in templates."""

    runtime_path, template_path = match_analysis_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, MatchAnalysis, default=None)
    if template_path.exists():
        return load_model(template_path, MatchAnalysis, default=None)
    return None


def analyze_and_save_match(
    base_dir: Path | str,
    candidate_profile: CandidateProfile,
    job: JobListing,
    experience_units: list[ExperienceUnit] | None = None,
) -> MatchAnalysis:
    """Generate and save a draft match analysis without updating tracker status."""

    existing = load_match_analysis(base_dir, job.id)
    units = experience_units or []
    if existing and match_analysis_is_fresh(existing, candidate_profile, job, units):
        return existing

    analysis = analyze_match(candidate_profile, job, units)
    save_match_analysis(base_dir, analysis)
    return analysis


def mark_match_analysis_reviewed(analysis: MatchAnalysis) -> MatchAnalysis:
    """Return a reviewed match analysis copy."""

    reviewed = analysis.model_copy(deep=True)
    reviewed.review_status = "reviewed"
    return reviewed


def reject_match_analysis(analysis: MatchAnalysis) -> MatchAnalysis:
    """Return a rejected match analysis copy."""

    rejected = analysis.model_copy(deep=True)
    rejected.review_status = "rejected"
    return rejected


def update_tracker_for_match_analysis(
    base_dir: Path | str,
    analysis: MatchAnalysis,
) -> list[TrackerRecord]:
    """Apply reviewed or rejected match decisions to the runtime tracker."""

    jobs_index_path = runtime_jobs_index_path(base_dir)
    tracker_path = runtime_tracker_path(base_dir)
    tracker_records = load_model(jobs_index_path, list[TrackerRecord], default=[])

    for record in tracker_records:
        if record.job_id != analysis.job_id:
            continue
        record.match_score = analysis.match_score
        if analysis.review_status == "reviewed":
            record.status = "analyzed"
        elif analysis.review_status == "rejected":
            record.status = "rejected_by_user"
        break

    save_model(jobs_index_path, tracker_records)
    save_model(tracker_path, tracker_records)
    return tracker_records


def review_match_analysis(
    base_dir: Path | str,
    analysis: MatchAnalysis,
    *,
    accepted: bool,
) -> MatchAnalysis:
    """Persist a user match decision and update the tracker."""

    reviewed = (
        mark_match_analysis_reviewed(analysis)
        if accepted
        else reject_match_analysis(analysis)
    )
    save_match_analysis(base_dir, reviewed)
    update_tracker_for_match_analysis(base_dir, reviewed)
    return reviewed


def build_match_analysis_fingerprints(
    candidate_profile: CandidateProfile,
    job: JobListing,
    experience_units: list[ExperienceUnit],
) -> dict[str, str]:
    """Return source fingerprints used to identify stale match analysis."""

    return {
        "candidate_profile": _fingerprint_model(candidate_profile),
        "job": _fingerprint_model(job),
        "experience_units": _fingerprint_model(experience_units),
    }


def match_analysis_is_fresh(
    analysis: MatchAnalysis,
    candidate_profile: CandidateProfile,
    job: JobListing,
    experience_units: list[ExperienceUnit],
) -> bool:
    """Return whether a saved match analysis matches current source inputs."""

    return analysis.source_fingerprints == build_match_analysis_fingerprints(
        candidate_profile,
        job,
        experience_units,
    )


def _candidate_skills(candidate_profile: CandidateProfile) -> list[str]:
    profile_data = candidate_profile.candidate_profile
    skills = list(profile_data.cv_extracted.skills)
    for item in [
        *profile_data.cv_extracted.work_experience,
        *profile_data.cv_extracted.projects,
        *profile_data.cv_extracted.certifications,
    ]:
        skills.extend(_technical_terms_from_text(item))
    return _dedupe_text(skills)


def _candidate_evidence_text(
    candidate_profile: CandidateProfile,
    candidate_skills: list[str],
) -> str:
    profile_data = candidate_profile.candidate_profile
    return " ".join(
        [
            " ".join(candidate_skills),
            " ".join(profile_data.cv_extracted.work_experience),
            " ".join(profile_data.cv_extracted.projects),
            " ".join(profile_data.cv_extracted.certifications),
        ]
    )


def _job_skill_requirements(job: JobListing) -> list[str]:
    explicit_skills = [
        *job.requirements,
        *job.nice_to_have_skills,
    ]
    if explicit_skills:
        return _dedupe_text(explicit_skills)

    fallback_terms = _technical_terms_from_text(_job_text(job))
    return _dedupe_text(fallback_terms)


def _job_text(job: JobListing) -> str:
    return " ".join(
        item
        for item in [
            job.title,
            job.company,
            job.location or "",
            job.remote_policy or "",
            job.description or "",
            " ".join(job.requirements),
            " ".join(job.responsibilities),
            " ".join(job.nice_to_have_skills),
            job.salary or "",
            json.dumps(job.job_details, ensure_ascii=True, sort_keys=True),
        ]
        if item
    )


def _role_match_ratio(candidate_profile: CandidateProfile, job: JobListing) -> float:
    target_roles = candidate_profile.candidate_profile.candidate_preferences.target_roles
    if not target_roles:
        return 0.0
    job_title = job.title.casefold()
    best_ratio = 0.0
    for target_role in target_roles:
        target = target_role.casefold().strip()
        if not target:
            continue
        if target in job_title or job_title in target:
            best_ratio = max(best_ratio, 1.0)
            continue
        best_ratio = max(best_ratio, _token_overlap_ratio(target, job_title))
    return best_ratio


def _skill_match_ratio(
    matched_skills: list[str],
    missing_skills: list[str],
    job: JobListing,
) -> float:
    total = len(matched_skills) + len(missing_skills)
    if total:
        return len(matched_skills) / total
    return 0.5 if (job.description or "").strip() else 0.0


def _location_match_ratio(candidate_profile: CandidateProfile, job: JobListing) -> float:
    preferences = candidate_profile.candidate_profile.candidate_preferences
    target_locations = [location.casefold() for location in preferences.target_locations]
    remote_preferences = {item.casefold() for item in preferences.remote_preference}
    job_location = (job.location or "").casefold()
    remote_policy = (job.remote_policy or "").casefold()

    if "remote" in remote_preferences and "remote" in remote_policy:
        return 1.0
    if "hybrid" in remote_preferences and "hybrid" in remote_policy:
        return 1.0
    if "onsite" in remote_preferences and any(
        term in remote_policy for term in ("onsite", "on-site", "office")
    ):
        return 1.0
    if "remote" in remote_preferences and "hybrid" in remote_policy:
        return 0.75
    if "hybrid" in remote_preferences and "remote" in remote_policy:
        return 0.75
    if any(location and location in job_location for location in target_locations):
        return 1.0
    if any(location in {"remote", "anywhere"} for location in target_locations):
        return 0.75 if "remote" in remote_policy or "hybrid" in remote_policy else 0.25
    return 0.25 if job_location else 0.0


def _constraint_match_ratio(candidate_profile: CandidateProfile, job: JobListing) -> float:
    preferences = candidate_profile.candidate_profile.candidate_preferences
    job_text = _job_text(job).casefold()
    authorization = preferences.work_authorization.casefold()

    if authorization == "eu_authorized":
        if any(term in job_text for term in ("visa sponsorship", "sponsorship required")):
            return 0.75
        return 1.0
    if authorization == "eu_sponsorship_required":
        if any(term in job_text for term in ("sponsorship", "visa")):
            return 0.75
        return 0.25
    return 0.5


def _completeness_ratio(candidate_profile: CandidateProfile, job: JobListing) -> float:
    profile_data = candidate_profile.candidate_profile
    earned = 0.0
    if profile_data.source_documents.cv.parsed:
        earned += 0.4
    if (job.description or "").strip():
        earned += 0.3
    if job.requirements:
        earned += 0.2
    if job.apply_url is not None:
        earned += 0.1
    return min(earned, 1.0)


def _relevant_experience_evidence(
    experience_units: list[ExperienceUnit],
    matched_skills: list[str],
    job: JobListing,
) -> tuple[list[str], list[str]]:
    matched_keys = {_skill_key(skill) for skill in matched_skills}
    job_terms = {_skill_key(term) for term in _technical_terms_from_text(_job_text(job))}
    evidence: list[str] = []
    unit_ids: list[str] = []
    for unit in experience_units:
        unit_skill_keys = {_skill_key(skill) for skill in unit.skills}
        overlap = (matched_keys | job_terms) & unit_skill_keys
        if not overlap:
            continue
        unit_ids.append(unit.id)
        evidence.append(f"{unit.title}: {unit.summary}")
    return evidence[:5], unit_ids[:5]


def _weak_points(
    candidate_profile: CandidateProfile,
    job: JobListing,
    missing_skills: list[str],
) -> list[str]:
    weak_points: list[str] = []
    if missing_skills:
        weak_points.append("Missing or unproven skills: " + ", ".join(missing_skills[:6]))
    if _location_match_ratio(candidate_profile, job) < 0.75:
        weak_points.append("Location or remote-work preference is not a strong match.")
    if _constraint_match_ratio(candidate_profile, job) < 0.75:
        weak_points.append("Work authorization or sponsorship constraints need review.")
    if not (job.description or "").strip():
        weak_points.append("Job description is incomplete, so the match may be under-scored.")
    return weak_points


def _positioning_summary(
    candidate_profile: CandidateProfile,
    job: JobListing,
    matched_skills: list[str],
    weak_points: list[str],
) -> str:
    target_roles = candidate_profile.candidate_profile.candidate_preferences.target_roles
    role_text = target_roles[0] if target_roles else "the target role"
    if matched_skills:
        strengths = ", ".join(matched_skills[:4])
        return (
            f"Position the candidate as a {role_text} fit for {job.title}, "
            f"leading with {strengths}."
        )
    if weak_points:
        return (
            f"Position the application cautiously for {job.title}; reviewer should "
            "address the main weak points before generating final material."
        )
    return f"Position the candidate around directly relevant experience for {job.title}."


def _application_strategy(
    job: JobListing,
    matched_skills: list[str],
    missing_skills: list[str],
    weak_points: list[str],
) -> list[str]:
    strategy: list[str] = []
    if matched_skills:
        strategy.append("Lead with matched skills: " + ", ".join(matched_skills[:5]) + ".")
    if missing_skills:
        strategy.append(
            "Bridge missing skills honestly with adjacent experience: "
            + ", ".join(missing_skills[:5])
            + "."
        )
    if job.remote_policy:
        strategy.append(f"Address the stated work model: {job.remote_policy}.")
    if weak_points:
        strategy.append("Use the package review step to resolve weak points before applying.")
    return strategy or ["Use the reviewed profile and job description to keep the package concise."]


def _analysis_blockers(candidate_profile: CandidateProfile, job: JobListing) -> list[str]:
    blockers: list[str] = []
    if not candidate_profile.candidate_profile.cv_extracted.skills:
        blockers.append("Candidate CV skills are missing, so skill matching is limited.")
    if not candidate_profile.candidate_profile.candidate_preferences.target_roles:
        blockers.append("Candidate target roles are missing, so role matching is limited.")
    if not job.requirements and not job.description:
        blockers.append("Job requirements and description are missing.")
    return blockers


def _technical_terms_from_text(value: str) -> list[str]:
    terms: list[str] = []
    for phrase in re.split(r"[,;/\n|]+", value):
        cleaned = phrase.strip(" .:-()[]{}")
        if 2 <= len(cleaned) <= 40 and _looks_like_skill(cleaned):
            terms.append(cleaned)
    return terms


def _looks_like_skill(value: str) -> bool:
    lowered = value.casefold()
    skill_keywords = {
        "python",
        "sql",
        "api",
        "apis",
        "streamlit",
        "automation",
        "dashboard",
        "dashboards",
        "data analysis",
        "excel",
        "git",
        "langgraph",
        "openai",
        "browser use",
        "stakeholder management",
        "workflow automation",
    }
    if lowered in skill_keywords:
        return True
    return bool(re.search(r"\b(python|sql|api|automation|dashboard|analysis|git)\b", lowered))


def _contains_phrase(haystack: str, phrase: str) -> bool:
    normalized_phrase = phrase.casefold().strip()
    if not normalized_phrase:
        return False
    return normalized_phrase in haystack.casefold()


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(_word_tokens(left))
    right_tokens = set(_word_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _word_tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.casefold()) if token]


def _skill_key(value: str) -> str:
    return " ".join(_word_tokens(value))


def _display_skill(value: str) -> str:
    normalized = value.strip()
    if normalized.isupper() or len(normalized) <= 3:
        return normalized
    return normalized[:1].upper() + normalized[1:]


def _dedupe_text(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _fingerprint_model(value: Any) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    elif isinstance(value, list):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
    else:
        payload = value
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
