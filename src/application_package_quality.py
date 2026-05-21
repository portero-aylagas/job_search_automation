"""Quality review helpers for generated application packages."""

from __future__ import annotations

import re
from typing import Any

from src.schemas import ApplicationPackage, CandidateProfile, JobListing


def apply_application_package_quality_checks(
    package: ApplicationPackage,
    candidate_profile: CandidateProfile,
    job: JobListing,
) -> ApplicationPackage:
    """Flag generated artifacts that need human review before use."""

    checked_package = package.model_copy(deep=True)
    candidate_evidence = _candidate_evidence_text(candidate_profile)
    unsupported_terms = _unsupported_requirement_terms(job, candidate_evidence)
    review_items: list[str] = []

    for artifact in checked_package.artifacts:
        findings = [
            *_sensitive_answer_findings(artifact),
            *_unsupported_claim_findings(artifact.content, unsupported_terms),
        ]
        if not findings:
            continue

        metadata = dict(artifact.metadata)
        metadata["quality_findings"] = _dedupe(
            [
                *[str(item) for item in metadata.get("quality_findings", [])],
                *findings,
            ]
        )
        artifact.metadata = metadata
        if artifact.status != "manually_edited":
            artifact.status = "needs_review"
        review_items.extend(
            f"Review generated artifact '{artifact.label}': {finding}"
            for finding in findings
        )

    if review_items:
        checked_package.status = "needs_review"
        checked_package.missing_information = _dedupe(
            [*checked_package.missing_information, *review_items]
        )
        checked_package.generation_notes = _dedupe(
            [
                *checked_package.generation_notes,
                "Quality checks flagged generated content for reviewer confirmation.",
            ]
        )
    return checked_package


def is_sensitive_or_user_decision_field(value: str) -> bool:
    """Return whether a field requires direct human input or consent."""

    normalized = value.casefold()
    decision_terms = (
        "referral",
        "recommendation code",
        "empfehlung",
        "internal",
        "employee",
        "severe disability",
        "disability",
        "behinderung",
        "consent",
        "privacy",
        "datenschutz",
        "einwilligung",
    )
    return any(term in normalized for term in decision_terms)


def _candidate_evidence_text(candidate_profile: CandidateProfile) -> str:
    profile_data = candidate_profile.candidate_profile
    extracted = profile_data.cv_extracted
    evidence_parts = [
        extracted.identity.full_name,
        extracted.identity.location,
        *extracted.work_experience,
        *extracted.education,
        *extracted.skills,
        *extracted.languages,
        *extracted.certifications,
        *extracted.projects,
        *extracted.references,
        *profile_data.candidate_preferences.target_roles,
    ]
    return " ".join(evidence_parts).casefold()


def _unsupported_requirement_terms(
    job: JobListing,
    candidate_evidence: str,
) -> list[str]:
    terms: list[str] = []
    for raw_term in [*job.requirements, *job.nice_to_have_skills]:
        term = _quality_term(raw_term)
        if not term:
            continue
        if term.casefold() not in candidate_evidence:
            terms.append(term)
    return _dedupe(terms)


def _quality_term(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" .,:;")
    if len(normalized) < 3:
        return ""
    if len(normalized.split()) > 4:
        return ""
    return normalized


def _sensitive_answer_findings(artifact: Any) -> list[str]:
    source_text = " ".join(
        str(value)
        for value in (
            artifact.label,
            artifact.source_prompt or "",
            artifact.source_requirement or "",
        )
        if value
    )
    if artifact.content.strip() and is_sensitive_or_user_decision_field(source_text):
        return ["Generated answer for a sensitive or user-decision field."]
    return []


def _unsupported_claim_findings(
    content: str,
    unsupported_terms: list[str],
) -> list[str]:
    findings: list[str] = []
    for term in unsupported_terms:
        if _content_claims_experience_with_term(content, term):
            findings.append(f"Claims experience with unsupported requirement: {term}")
    return findings


def _content_claims_experience_with_term(content: str, term: str) -> bool:
    escaped_term = re.escape(term)
    claim_pattern = re.compile(
        rf"\b("
        rf"experience\s+(?:with|in)|"
        rf"experienced\s+(?:with|in)|"
        rf"skilled\s+(?:with|in)|"
        rf"proficient\s+(?:with|in)|"
        rf"expert\s+(?:with|in)"
        rf")\s+{escaped_term}\b",
        re.IGNORECASE,
    )
    return bool(claim_pattern.search(content))


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped
