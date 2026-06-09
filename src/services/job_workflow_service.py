"""Shared job, workflow, and Browser Use actions for API and Karen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from src.app_workflow import (
    apply_resolution_details,
    extract_job_intake_data,
    get_application_package_blockers,
    lines_from_text,
    load_application_page_snapshot,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_jobs_index,
    load_normalized_job,
    validate_reviewed_apply_url,
    workflow_trace_payload,
)
from src.application_fill_plan import (
    generate_application_fill_plan,
    load_application_fill_plan,
    map_application_fields_with_llm,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.application_fill_plan_review import apply_fill_plan_review_submission
from src.application_package import (
    export_cover_letter_artifact,
    generate_application_package,
    load_application_package,
    save_application_package,
    update_tracker_for_application_package,
)
from src.application_requirements import (
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.browser_use_launcher import (
    BrowserUseLaunchError,
    BrowserUseOpenResult,
    open_apply_url_with_browser_use_fill_plan,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.job_intake import create_job_listing, persist_job_listing
from src.job_workspace import (
    apply_application_package_review_edits,
    apply_application_requirements_review_edits,
    get_apply_assistance_blockers,
    get_fill_plan_generation_blockers,
    mark_application_package_reviewed,
)
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData
from src.observability import traceable
from src.paths import RUNTIME_DATA_DIR
from src.schemas import (
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    TrackerRecord,
)
from src.tracker_status import (
    archive_tracker_record,
    purge_job_data,
    restore_tracker_record,
    update_manual_tracker_status,
    update_tracker_record,
)


class JobWorkflowServiceError(RuntimeError):
    """Raised when a shared job workflow action cannot complete."""


@dataclass(frozen=True)
class ReviewedJobInput:
    """Reviewed job-intake fields from the URL-first form."""

    source_url: str
    extracted_data: ExtractedJobData
    apply_resolution: ApplyUrlResolution | None
    title: str
    company: str
    location: str = ""
    remote_policy: str = ""
    apply_url: str = ""
    salary: str = ""
    posted_date: str = ""
    source_job_id: str = ""
    description: str = ""
    requirements: str = ""
    responsibilities: str = ""
    nice_to_have_skills: str = ""
    dynamic_fields: list[dict[str, object]] | None = None


def extract_job_url(source_url: str):
    """Extract job intake data and apply-link candidates from a source URL."""

    try:
        return _extract_job_url_traced(source_url)
    except (RuntimeError, ValueError) as exc:
        raise JobWorkflowServiceError(str(exc)) from exc


@traceable(
    "Job Intake",
    tags=("workflow:job_intake", "job-search-automation"),
    metadata=lambda source_url: {
        "workflow_key": "job_intake",
        "source": "job_intake",
    },
)
def _extract_job_url_traced(source_url: str):
    """Extract job intake data inside a named LangSmith parent trace."""

    return extract_job_intake_data(source_url)


def save_reviewed_job(
    base_dir: Path | str,
    reviewed_input: ReviewedJobInput,
) -> tuple[JobListing, Path]:
    """Persist reviewed job intake data and update the tracker."""

    try:
        validate_reviewed_apply_url(
            reviewed_input.apply_url,
            reviewed_input.source_url,
            reviewed_input.apply_resolution,
        )
        job = create_job_listing(
            title=reviewed_input.title,
            company=reviewed_input.company,
            source_url=reviewed_input.source_url,
            location=reviewed_input.location,
            remote_policy=reviewed_input.remote_policy,
            apply_url=reviewed_input.apply_url,
            description=reviewed_input.description,
            requirements=lines_from_text(reviewed_input.requirements),
            responsibilities=lines_from_text(reviewed_input.responsibilities),
            nice_to_have_skills=lines_from_text(reviewed_input.nice_to_have_skills),
            salary=reviewed_input.salary,
            posted_date=reviewed_input.posted_date,
            source_job_id=reviewed_input.source_job_id,
            job_details={
                "extraction_confidence": reviewed_input.extracted_data.confidence,
                "job_extraction_trace": workflow_trace_payload(
                    reviewed_input.extracted_data.workflow_trace
                ),
                "apply_url_resolution": apply_resolution_details(
                    reviewed_input.apply_url,
                    reviewed_input.source_url,
                    reviewed_input.apply_resolution,
                ),
                "dynamic_fields": [
                    field
                    for field in reviewed_input.dynamic_fields or []
                    if field.get("name") or field.get("value")
                ],
            },
        )
    except (ValueError, ValidationError) as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    job_path = persist_job_listing(base_dir, job)
    return job, job_path


def update_tracker_status(base_dir: Path | str, job_id: str, status: str) -> TrackerRecord:
    """Update one tracker status manually."""

    ensure_job_is_active(base_dir, job_id)
    try:
        records = update_manual_tracker_status(base_dir, job_id, status)
    except ValueError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    record = next((item for item in records if item.job_id == job_id), None)
    if record is None:
        raise JobWorkflowServiceError("Tracker record not found.")
    return record


def archive_job(base_dir: Path | str, job_id: str) -> TrackerRecord | None:
    """Archive one job from active views."""

    try:
        records = archive_tracker_record(base_dir, job_id)
    except ValueError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    return next((item for item in records if item.job_id == job_id), None)


def restore_job(base_dir: Path | str, job_id: str) -> TrackerRecord | None:
    """Restore one archived job to active views."""

    try:
        records = restore_tracker_record(base_dir, job_id)
    except ValueError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    return next((item for item in records if item.job_id == job_id), None)


def delete_job_data(base_dir: Path | str, job_id: str) -> list[TrackerRecord]:
    """Permanently delete one job's local data and tracker entry."""

    try:
        return purge_job_data(base_dir, job_id)
    except ValueError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc


def discover_application_requirements(
    base_dir: Path | str,
    job_id: str,
) -> ApplicationRequirements:
    """Discover and persist application requirements for a reviewed apply URL."""

    job = require_job(base_dir, job_id)
    try:
        discovery_state = _run_requirements_discovery_traced(job)
        requirements = discovery_state["requirements"]
        save_application_page_snapshot(base_dir, job.id, discovery_state["snapshot"])
        save_application_requirements(base_dir, requirements)
    except (RuntimeError, ValueError) as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    return requirements


@traceable(
    "Requirements",
    tags=("workflow:jobs", "job-search-automation"),
    metadata=lambda job: _job_trace_metadata("requirements", "Requirements", job),
)
def _run_requirements_discovery_traced(job: JobListing) -> dict[str, object]:
    """Discover requirements inside a named LangSmith parent trace."""

    return run_requirements_discovery_graph(job)


def review_application_requirements(
    base_dir: Path | str,
    job_id: str,
    **review_fields: object,
) -> ApplicationRequirements:
    """Save structured requirements review edits."""

    ensure_job_is_active(base_dir, job_id)
    requirements = require_requirements(base_dir, job_id)
    try:
        reviewed = apply_application_requirements_review_edits(
            requirements,
            **review_fields,
        )
    except ValidationError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    save_application_requirements(base_dir, reviewed)
    return reviewed


def generate_reviewable_application_package(
    base_dir: Path | str,
    job_id: str,
) -> tuple[ApplicationPackage, Path, Path]:
    """Generate or regenerate an application package."""

    job = require_job(base_dir, job_id)
    requirements = load_application_requirements(base_dir, job.id)
    candidate_profile = load_candidate_profile(base_dir)
    blockers = get_application_package_blockers(candidate_profile, job, requirements)
    if blockers:
        raise JobWorkflowServiceError(
            "Complete all package prerequisites before generating application material."
        )
    try:
        package = _generate_application_package_traced(
            candidate_profile,
            load_experience_units(base_dir),
            job,
            requirements,
        )
        json_path, markdown_path = save_application_package(base_dir, package, job)
        update_tracker_for_application_package(base_dir, job.id, json_path)
    except RuntimeError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    return package, json_path, markdown_path


@traceable(
    "Application Package",
    tags=("workflow:jobs", "job-search-automation"),
    metadata=lambda candidate_profile, experience_units, job, requirements=None: (
        _job_trace_metadata("application_package", "Application Package", job)
    ),
)
def _generate_application_package_traced(
    candidate_profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None,
) -> ApplicationPackage:
    """Generate an application package inside a named LangSmith parent trace."""

    return generate_application_package(candidate_profile, experience_units, job, requirements)


def review_application_package(
    base_dir: Path | str,
    job_id: str,
    edits_by_artifact_id: dict[str, str],
) -> tuple[ApplicationPackage, Path, Path]:
    """Save artifact text edits and mark the package reviewed."""

    job = require_job(base_dir, job_id)
    package = require_package(base_dir, job_id)
    edited = apply_application_package_review_edits(package, edits_by_artifact_id)
    reviewed = mark_application_package_reviewed(edited)
    json_path, markdown_path = save_application_package(base_dir, reviewed, job)
    update_tracker_for_application_package(base_dir, job.id, json_path)
    return reviewed, json_path, markdown_path


def export_cover_letter(
    base_dir: Path | str,
    job_id: str,
    destination_folder: str,
) -> tuple[Path, Path, Path]:
    """Export the reviewed cover-letter artifact to the requested folder."""

    job = require_job(base_dir, job_id)
    package = require_package(base_dir, job_id)
    destination_text = destination_folder.strip()
    if not destination_text:
        raise JobWorkflowServiceError(
            "Choose a destination folder before exporting the cover letter."
        )
    try:
        exported_path = export_cover_letter_artifact(
            package,
            Path(destination_text).expanduser(),
        )
        json_path, markdown_path = save_application_package(base_dir, package, job)
        update_tracker_for_application_package(base_dir, job.id, json_path)
    except OSError as exc:
        raise JobWorkflowServiceError(f"Could not export cover letter artifact: {exc}") from exc
    if exported_path is None:
        raise JobWorkflowServiceError("No cover letter artifact is available to export.")
    return exported_path, json_path, markdown_path


def generate_reviewable_fill_plan(
    base_dir: Path | str,
    job_id: str,
) -> tuple[ApplicationFillPlan, Path]:
    """Generate or refresh the application fill plan."""

    ensure_job_is_active(base_dir, job_id)
    requirements = load_application_requirements(base_dir, job_id)
    package = load_application_package(base_dir, job_id)
    blockers = get_fill_plan_generation_blockers(requirements, package)
    if blockers or requirements is None or package is None:
        raise JobWorkflowServiceError("Complete fill plan prerequisites before generating.")
    job = require_job(base_dir, job_id)
    try:
        fill_plan = _generate_application_fill_plan_traced(
            load_candidate_profile(base_dir),
            requirements,
            package,
            job,
            page_snapshot=load_application_page_snapshot(base_dir, job_id),
            semantic_mapper=map_application_fields_with_llm,
        )
        saved_path = save_application_fill_plan(base_dir, fill_plan)
    except RuntimeError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    return fill_plan, saved_path


@traceable(
    "Field Mapping",
    tags=("workflow:jobs", "job-search-automation"),
    metadata=lambda candidate_profile, requirements, package, job, **kwargs: _job_trace_metadata(
        "field_mapping",
        "Field Mapping",
        job,
    ),
)
def _generate_application_fill_plan_traced(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    job: JobListing,
    *,
    page_snapshot: object | None,
    semantic_mapper: object | None,
) -> ApplicationFillPlan:
    """Generate a fill plan inside a named LangSmith parent trace."""

    return generate_application_fill_plan(
        candidate_profile,
        requirements,
        package,
        page_snapshot=page_snapshot,
        semantic_mapper=semantic_mapper,
    )


def review_fill_plan(
    base_dir: Path | str,
    job_id: str,
    *,
    edited_values: dict[str, str],
    upload_paths_by_key: dict[str, str],
    needs_answer_values_by_key: dict[str, str],
    blocked_values_by_key: dict[str, str],
) -> ApplicationFillPlan:
    """Save structured fill-plan edits and mark the plan reviewed."""

    ensure_job_is_active(base_dir, job_id)
    fill_plan = require_fill_plan(base_dir, job_id)
    edited = apply_fill_plan_review_submission(
        fill_plan,
        {
            "edited_values": edited_values,
            "upload_paths_by_key": upload_paths_by_key,
            "needs_answer_values_by_key": needs_answer_values_by_key,
            "blocked_values_by_key": blocked_values_by_key,
        },
    )
    try:
        reviewed = mark_application_fill_plan_reviewed(edited)
    except ValueError as exc:
        save_application_fill_plan(base_dir, edited)
        raise JobWorkflowServiceError(str(exc)) from exc
    save_application_fill_plan(base_dir, reviewed)
    update_tracker_record(base_dir, job_id, status="ready_to_apply")
    return reviewed


def launch_apply_assistance(
    base_dir: Path | str,
    job_id: str,
    *,
    final_submit: bool = False,
    startup_wait_seconds: float = 0.0,
) -> BrowserUseOpenResult:
    """Start Browser Use apply assistance for a reviewed job."""

    job = require_job(base_dir, job_id)
    candidate_profile = load_candidate_profile(base_dir)
    requirements = load_application_requirements(base_dir, job.id)
    package = load_application_package(base_dir, job.id)
    fill_plan = load_application_fill_plan(base_dir, job.id)
    blockers = get_apply_assistance_blockers(
        job,
        requirements,
        package,
        fill_plan,
        candidate_profile=candidate_profile,
    )
    if blockers:
        raise JobWorkflowServiceError(
            "Complete the required review steps before opening the apply flow."
        )
    if fill_plan is None:
        raise JobWorkflowServiceError(
            "Generate and review the application fill plan before applying."
        )
    browser_use_log_dir = Path(base_dir) / RUNTIME_DATA_DIR / "browser_use"
    try:
        result = _launch_apply_assistance_traced(
            str(job.apply_url),
            fill_plan=fill_plan,
            job=job,
            log_dir=browser_use_log_dir,
            startup_wait_seconds=startup_wait_seconds,
            candidate_profile=candidate_profile,
            requirements=requirements,
            package=package,
            final_submit=final_submit,
        )
    except BrowserUseLaunchError as exc:
        raise JobWorkflowServiceError(str(exc)) from exc
    update_tracker_record(base_dir, job.id, status="agent_assistance_attempted")
    return result


@traceable(
    "Browser Automation",
    tags=("workflow:browser_automation", "job-search-automation"),
    metadata=lambda url, *, fill_plan, job, **kwargs: _job_trace_metadata(
        "browser_automation",
        "Browser Automation",
        job,
    ),
)
def _launch_apply_assistance_traced(
    url: str,
    *,
    fill_plan: ApplicationFillPlan,
    job: JobListing,
    log_dir: Path,
    startup_wait_seconds: float,
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    final_submit: bool,
) -> BrowserUseOpenResult:
    """Launch Browser Use inside a named LangSmith parent trace."""

    return open_apply_url_with_browser_use_fill_plan(
        url,
        fill_plan=fill_plan,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        candidate_profile=candidate_profile,
        requirements=requirements,
        package=package,
        final_submit=final_submit,
        trace_metadata=_job_trace_metadata("browser_automation", "Browser Automation", job),
    )


def stop_active_browser_session(base_dir: Path | str) -> bool:
    """Stop the active Browser Use session."""

    browser_use_log_dir = Path(base_dir) / RUNTIME_DATA_DIR / "browser_use"
    return stop_browser_use_session(browser_use_log_dir)


def kill_browser_processes(base_dir: Path | str) -> int:
    """Kill all Browser Use process groups started by this project."""

    browser_use_log_dir = Path(base_dir) / RUNTIME_DATA_DIR / "browser_use"
    return stop_all_browser_use_processes(browser_use_log_dir)


def _job_trace_metadata(
    workflow_subcategory_key: str,
    workflow_subcategory_label: str,
    job: JobListing,
) -> dict[str, object]:
    """Return safe job metadata for LangSmith workflow grouping."""

    metadata = {
        "workflow_key": "jobs"
        if workflow_subcategory_key
        in {"apply_url_ranking", "requirements", "application_package", "field_mapping"}
        else workflow_subcategory_key,
        "job_id": job.id,
        "job_title": job.title,
        "company": job.company,
        "source": "job_workflow",
    }
    if metadata["workflow_key"] == "jobs":
        metadata["workflow_subcategory_key"] = workflow_subcategory_key
        metadata["workflow_subcategory_label"] = workflow_subcategory_label
    if workflow_subcategory_key == "browser_automation":
        display_name = _browser_automation_display_name(job)
        if display_name:
            metadata["display_name"] = display_name
    return metadata


def _browser_automation_display_name(job: JobListing) -> str:
    """Return a Browser Automation display name from saved job context."""

    job_title = job.title.strip()
    company = job.company.strip()
    if company and job_title:
        return f"Browser Automation: {company} / {job_title}"
    if job_title:
        return f"Browser Automation: {job_title}"
    if job.id.strip():
        return f"Browser Automation: {job.id.strip()}"
    return "Browser Automation"


def require_job(base_dir: Path | str, job_id: str) -> JobListing:
    """Load a saved normalized job or raise a service error."""

    ensure_job_is_active(base_dir, job_id)
    job = load_normalized_job(base_dir, job_id)
    if job is None:
        raise JobWorkflowServiceError("Job not found.")
    return job


def ensure_job_is_active(base_dir: Path | str, job_id: str) -> None:
    """Reject direct workflow access for archived jobs."""

    record = next((item for item in load_jobs_index(base_dir) if item.job_id == job_id), None)
    if record is not None and record.archived_at:
        raise JobWorkflowServiceError(
            "Restore this archived job before running workflow actions."
        )


def require_requirements(base_dir: Path | str, job_id: str) -> ApplicationRequirements:
    """Load application requirements or raise a service error."""

    requirements = load_application_requirements(base_dir, job_id)
    if requirements is None:
        raise JobWorkflowServiceError("Application requirements not found.")
    return requirements


def require_package(base_dir: Path | str, job_id: str) -> ApplicationPackage:
    """Load an application package or raise a service error."""

    package = load_application_package(base_dir, job_id)
    if package is None:
        raise JobWorkflowServiceError("Application package not found.")
    return package


def require_fill_plan(base_dir: Path | str, job_id: str) -> ApplicationFillPlan:
    """Load an application fill plan or raise a service error."""

    fill_plan = load_application_fill_plan(base_dir, job_id)
    if fill_plan is None:
        raise JobWorkflowServiceError("Application fill plan not found.")
    return fill_plan
