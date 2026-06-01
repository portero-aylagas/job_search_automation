"""UI-free workflow helpers shared by the API layer and tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.apply_url_resolution import resolve_apply_url_agentically
from src.candidate_profile import (
    normalize_candidate_profile_documents,
    validate_candidate_profile,
)
from src.job_intake import validate_apply_url
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData, extract_job_data_from_url
from src.paths import (
    application_page_snapshot_paths,
    application_requirements_paths,
    candidate_profile_path,
    experience_units_paths,
    jobs_index_paths,
    legacy_profile_path,
    normalized_job_paths,
    runtime_candidate_profile_path,
)
from src.sample_data import bootstrap_sample_data
from src.schemas import (
    AIWorkflowTrace,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    TrackerRecord,
)
from src.storage import load_model, save_model


class ApplyUrlResolver(Protocol):
    """Callable contract for resolving a job-preserving application URL."""

    def __call__(
        self,
        source_url: str,
        *,
        title: str,
        company: str,
        source_job_id: str,
    ) -> ApplyUrlResolution:
        """Resolve an application URL candidate from reviewed job identity."""
        ...


@dataclass(frozen=True)
class JobIntakeExtractionResult:
    """Combined result from job extraction and apply URL resolution."""

    extracted: ExtractedJobData
    apply_resolution: ApplyUrlResolution


def load_app_data(base_dir: Path | str) -> tuple[CandidateProfile, list[TrackerRecord]]:
    """Bootstrap sample files, then load the active profile and job index."""

    bootstrap_sample_data(base_dir)
    return load_candidate_profile(base_dir), load_jobs_index(base_dir)


def extract_job_intake_data(
    source_url: str,
    *,
    extractor: Callable[[str], ExtractedJobData] = extract_job_data_from_url,
    resolver: ApplyUrlResolver = resolve_apply_url_agentically,
) -> JobIntakeExtractionResult:
    """Extract reviewed job data and resolve the apply URL with injectable steps."""

    extracted = extractor(source_url)
    apply_resolution = resolver(
        source_url,
        title=extracted.title,
        company=extracted.company,
        source_job_id=extracted.source_job_id,
    )
    return JobIntakeExtractionResult(
        extracted=extracted,
        apply_resolution=apply_resolution,
    )


def load_candidate_profile(base_dir: Path | str) -> CandidateProfile:
    """Load the active candidate profile, falling back through legacy paths."""

    active_path = candidate_profile_path(base_dir)
    runtime_path = runtime_candidate_profile_path(base_dir)
    legacy_path = legacy_profile_path(base_dir)

    if active_path.exists():
        return normalize_candidate_profile_documents(load_model(active_path, CandidateProfile))
    if runtime_path.exists():
        return normalize_candidate_profile_documents(load_model(runtime_path, CandidateProfile))
    if legacy_path.exists():
        return normalize_candidate_profile_documents(load_model(legacy_path, CandidateProfile))
    return CandidateProfile()


def save_candidate_profile(base_dir: Path | str, profile: CandidateProfile) -> Path:
    """Persist the reviewed candidate profile to the active profile path."""

    target = candidate_profile_path(base_dir)
    save_model(target, normalize_candidate_profile_documents(profile))
    return target


def load_normalized_job(base_dir: Path | str, job_id: str) -> JobListing | None:
    """Load a normalized job from runtime data or checked-in templates."""

    runtime_path, template_path = normalized_job_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, JobListing, default=None)
    if template_path.exists():
        return load_model(template_path, JobListing, default=None)
    return None


def load_application_requirements(
    base_dir: Path | str,
    job_id: str,
) -> ApplicationRequirements | None:
    """Load application requirements from runtime data or templates."""

    runtime_path, template_path = application_requirements_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationRequirements, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationRequirements, default=None)
    return None


def load_application_page_snapshot(
    base_dir: Path | str,
    job_id: str,
) -> ApplicationPageSnapshot | None:
    """Load an application-page snapshot from runtime data or templates."""

    runtime_path, template_path = application_page_snapshot_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationPageSnapshot, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationPageSnapshot, default=None)
    return None


def load_experience_units(base_dir: Path | str) -> list[ExperienceUnit]:
    """Load reusable experience units from runtime data or templates."""

    runtime_path, template_path = experience_units_paths(base_dir)
    if runtime_path.exists():
        return load_model(runtime_path, list[ExperienceUnit], default=[])
    if template_path.exists():
        return load_model(template_path, list[ExperienceUnit], default=[])
    return []


def load_jobs_index(base_dir: Path | str) -> list[TrackerRecord]:
    """Load tracker records using the runtime-first lookup order."""

    runtime_jobs_index, runtime_tracker, template_jobs_index, template_tracker = jobs_index_paths(
        base_dir
    )
    if runtime_jobs_index.exists():
        return load_model(runtime_jobs_index, list[TrackerRecord], default=[])
    if runtime_tracker.exists():
        return load_model(runtime_tracker, list[TrackerRecord], default=[])
    if template_jobs_index.exists():
        return load_model(template_jobs_index, list[TrackerRecord], default=[])
    if template_tracker.exists():
        return load_model(template_tracker, list[TrackerRecord], default=[])
    return []


def get_application_package_blockers(
    candidate_profile: CandidateProfile,
    job: JobListing,
    requirements: ApplicationRequirements | None,
) -> list[str]:
    """Return workflow blockers that prevent application package generation."""

    blockers: list[str] = []
    profile_errors = validate_candidate_profile(candidate_profile)

    if profile_errors:
        blockers.append("Complete the candidate profile: " + ", ".join(profile_errors))
    if not candidate_profile.candidate_profile.source_documents.cv.parsed:
        blockers.append("Parse the candidate CV before generating application material.")
    if not (job.description or "").strip():
        blockers.append(
            "Parse and save the job description before generating application material."
        )
    if requirements is None:
        blockers.append("Discover application requirements before generating application material.")
    elif requirements.status != "discovered" or not requirements.job_preserving:
        blockers.append("Resolve application requirements before generating application material.")
    elif requirements.review_status != "reviewed":
        blockers.append(
            "Review the application requirements before generating application material."
        )

    return blockers


def mark_requirements_reviewed(
    requirements: ApplicationRequirements,
) -> ApplicationRequirements:
    """Return a reviewed copy of discovered application requirements."""

    reviewed_requirements = requirements.model_copy(deep=True)
    reviewed_requirements.review_status = "reviewed"
    return reviewed_requirements


def workflow_trace_payload(trace: AIWorkflowTrace | None) -> dict[str, object] | None:
    """Convert optional workflow trace metadata into a JSON-ready payload."""

    if trace is None:
        return None
    return trace.model_dump(mode="json")


def resolved_apply_url(source_url: str, resolution: ApplyUrlResolution | None) -> str:
    """Return a resolver-verified apply URL, or an empty string when unusable."""

    if resolution is None or resolution.status != "resolved":
        return ""

    candidate = resolution.apply_url.strip()
    if not candidate:
        return ""

    try:
        validate_apply_url(candidate, source_url)
    except ValueError:
        return ""
    return candidate


def validate_reviewed_apply_url(
    apply_url: str,
    source_url: str,
    resolution: ApplyUrlResolution | None,
) -> None:
    """Validate the reviewed apply URL against any resolver-verified result."""

    validate_apply_url(apply_url, source_url)
    verified_url = resolved_apply_url(source_url, resolution)
    if verified_url and apply_url.strip() != verified_url:
        raise ValueError("Apply URL must match the verified job-preserving application URL.")


def apply_resolution_details(
    apply_url: str,
    source_url: str,
    resolution: ApplyUrlResolution | None,
) -> dict[str, object]:
    """Return resolver metadata for persistence with the reviewed job details."""

    verified_url = resolved_apply_url(source_url, resolution)
    manual_override = bool(apply_url.strip()) and apply_url.strip() != verified_url
    if resolution is None:
        return {
            "status": "manual_review",
            "apply_url": apply_url.strip(),
            "verified_by_resolver": False,
            "manual_override": manual_override,
            "notes": "Apply URL was entered manually and was not verified by the resolver.",
            "evidence": [],
            "rejected_candidates": [],
            "confidence": "low",
        }

    details = resolution.model_dump(mode="json")
    details["verified_by_resolver"] = bool(verified_url)
    details["manual_override"] = manual_override
    if manual_override:
        details["manual_apply_url"] = apply_url.strip()
    return details


def apply_url_review_messages(
    extracted_apply_url: str,
    source_url: str,
    final_apply_url: str,
) -> dict[str, list[str]]:
    """Build review messages for unresolved or manually entered apply URLs."""

    messages: dict[str, list[str]] = {"errors": [], "warnings": [], "info": []}
    if final_apply_url:
        return messages

    if extracted_apply_url:
        try:
            validate_apply_url(extracted_apply_url, source_url)
        except ValueError as exc:
            messages["errors"].append(str(exc))
        messages["warnings"].append(
            "The extracted apply URL was not verified by the apply-link resolver."
        )

    messages["info"].append(
        "You can paste the application URL manually. It will be saved as a "
        "manual review URL and checked during requirements discovery."
    )
    return messages


def lines_from_text(value: str) -> list[str]:
    """Split multiline review text into trimmed non-empty list items."""

    return [line.strip("-• \t") for line in value.splitlines() if line.strip("-• \t")]
