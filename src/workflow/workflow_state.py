"""Persisted workflow state loading for the known-job application flow."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from src.app_workflow import (
    get_application_package_blockers,
    load_application_requirements,
    load_candidate_profile,
    load_jobs_index,
    load_normalized_job,
)
from src.application_fill_plan import (
    get_application_fill_plan_review_blockers,
    load_application_fill_plan,
)
from src.application_package import load_application_package
from src.candidate_profile import validate_candidate_profile
from src.job_workspace import (
    get_apply_assistance_blockers,
    get_fill_plan_generation_blockers,
)


class CurrentWorkflowState(BaseModel):
    """Current persisted workflow facts used by Karen's deterministic planner."""

    selected_job_id: str | None = None
    job_exists: bool = False
    job_archived: bool = False
    candidate_profile_complete: bool = False
    candidate_profile_blockers: list[str] = Field(default_factory=list)
    requirements_exists: bool = False
    requirements_status: str | None = None
    requirements_review_status: str | None = None
    requirements_job_preserving: bool | None = None
    package_exists: bool = False
    package_status: str | None = None
    fill_plan_exists: bool = False
    fill_plan_review_status: str | None = None
    current_blockers: list[str] = Field(default_factory=list)
    pending_gate: str | None = None
    next_allowed_actions: list[str] = Field(default_factory=list)
    route_hint: str | None = None


def load_current_workflow_state(
    base_dir: Path | str,
    selected_job_id: str | None,
) -> CurrentWorkflowState:
    """Load persisted workflow artifacts and current blockers for one job."""

    if not selected_job_id:
        return CurrentWorkflowState(
            selected_job_id=None,
            current_blockers=["Select a job before running the workflow."],
            pending_gate="select_job",
            route_hint="Jobs",
        )

    base_path = Path(base_dir)
    tracker_record = next(
        (record for record in load_jobs_index(base_path) if record.job_id == selected_job_id),
        None,
    )
    job_archived = bool(tracker_record and tracker_record.archived_at)
    job = load_normalized_job(base_path, selected_job_id)
    profile = load_candidate_profile(base_path)
    profile_blockers = validate_candidate_profile(profile)

    state = CurrentWorkflowState(
        selected_job_id=selected_job_id,
        job_exists=job is not None,
        job_archived=job_archived,
        candidate_profile_complete=not profile_blockers,
        candidate_profile_blockers=profile_blockers,
    )
    if job_archived:
        state.current_blockers = ["Restore this archived job before running workflow actions."]
        state.route_hint = "Tracker"
        return state
    if job is None:
        state.current_blockers = ["Reviewed normalized job data is missing."]
        state.route_hint = "Job Intake"
        return state

    requirements = load_application_requirements(base_path, selected_job_id)
    package = load_application_package(base_path, selected_job_id)
    fill_plan = load_application_fill_plan(base_path, selected_job_id)

    state.requirements_exists = requirements is not None
    state.requirements_status = requirements.status if requirements is not None else None
    state.requirements_review_status = (
        requirements.review_status if requirements is not None else None
    )
    state.requirements_job_preserving = (
        requirements.job_preserving if requirements is not None else None
    )
    state.package_exists = package is not None
    state.package_status = package.status if package is not None else None
    state.fill_plan_exists = fill_plan is not None
    state.fill_plan_review_status = fill_plan.review_status if fill_plan is not None else None

    if requirements is None:
        if job.apply_url is None:
            state.current_blockers = [
                "Apply URL is required before requirements discovery.",
            ]
            state.route_hint = "Job Intake"
        else:
            state.next_allowed_actions = ["discover_requirements"]
        return state

    if requirements.status != "discovered" or not requirements.job_preserving:
        reason = requirements.blocked_reason or (
            "Application requirements must preserve the selected job before review."
        )
        state.current_blockers = [reason]
        state.pending_gate = "requirements_review"
        state.route_hint = "Jobs"
        return state

    if requirements.review_status != "reviewed":
        state.pending_gate = "requirements_review"
        state.next_allowed_actions = ["review_requirements", "discover_requirements"]
        state.route_hint = "Jobs"
        return state

    if package is None:
        blockers = get_application_package_blockers(profile, job, requirements)
        state.current_blockers = blockers
        state.route_hint = _route_for_blockers(blockers)
        if not blockers:
            state.next_allowed_actions = ["generate_application_package"]
        return state

    if package.status == "rejected":
        state.current_blockers = [
            "Regenerate or manually edit the rejected application package.",
        ]
        state.pending_gate = "package_review"
        state.route_hint = "Jobs"
        return state

    if package.status != "approved":
        state.pending_gate = "package_review"
        state.next_allowed_actions = [
            "review_application_package",
            "generate_application_package",
        ]
        state.route_hint = "Jobs"
        return state

    if fill_plan is None:
        blockers = get_fill_plan_generation_blockers(requirements, package)
        state.current_blockers = blockers
        state.route_hint = _route_for_blockers(blockers)
        if not blockers:
            state.next_allowed_actions = ["generate_fill_plan"]
        return state

    fill_review_blockers = get_application_fill_plan_review_blockers(fill_plan)
    if fill_review_blockers:
        state.current_blockers = fill_review_blockers
        state.pending_gate = "fill_plan_review"
        state.route_hint = "Jobs"
        return state

    if fill_plan.review_status != "reviewed":
        state.pending_gate = "fill_plan_review"
        state.next_allowed_actions = ["review_fill_plan", "generate_fill_plan"]
        state.route_hint = "Jobs"
        return state

    apply_blockers = get_apply_assistance_blockers(
        job,
        requirements,
        package,
        fill_plan,
        candidate_profile=profile,
    )
    if apply_blockers:
        state.current_blockers = apply_blockers
        state.route_hint = _route_for_blockers(apply_blockers)
        return state

    state.pending_gate = "browser_use_launch"
    state.next_allowed_actions = [
        "prepare_apply_assistance",
        "launch_browser_use",
        "prepare_manual_application",
    ]
    state.route_hint = "Jobs"
    return state


def _route_for_blockers(blockers: list[str]) -> str | None:
    if not blockers:
        return None
    text = " ".join(blockers).casefold()
    if "candidate profile" in text or "gender" in text or "upload cv" in text:
        return "Candidate Profile"
    if "apply url" in text or "normalized job" in text:
        return "Job Intake"
    if "tracker" in text or "archived" in text:
        return "Tracker"
    return "Jobs"

