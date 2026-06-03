"""Shared workflow action registry for UI metadata and Karen execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from src.agents.karen.policy import PermissionLevel
from src.app_workflow import load_application_requirements
from src.application_fill_plan import load_application_fill_plan
from src.application_fill_plan_review import build_fill_plan_review_submission_from_defaults
from src.schemas import (
    ApplicationFormField,
    ApplicationRequirementFinding,
    ApplicationScreeningQuestion,
)
from src.services import job_workflow_service as job_services
from src.services.job_workflow_service import JobWorkflowServiceError
from src.workflow.workflow_state import load_current_workflow_state

WorkflowHandler = Callable[[Path | str, str], "WorkflowActionResult"]


class WorkflowActionResult(BaseModel):
    """Result from one registered workflow action."""

    action_name: str
    status: str
    message: str
    blockers: list[str] = Field(default_factory=list)
    route_hint: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    event_details: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowAction:
    """Descriptor for a workflow action backed by existing service functions."""

    name: str
    label: str
    handler: WorkflowHandler
    permission_level: PermissionLevel
    requires_selected_job: bool = True
    requires_human_input: bool = False
    review_gate: bool = False
    external_effect: bool = False
    route_hint: str | None = None


def get_workflow_action(name: str | None) -> WorkflowAction | None:
    """Return registered workflow action metadata by name."""

    if not name:
        return None
    return WORKFLOW_ACTION_REGISTRY.get(name)


def execute_registered_action(
    action_name: str,
    base_dir: Path | str,
    selected_job_id: str | None,
) -> WorkflowActionResult:
    """Execute a registered action and normalize service-layer failures."""

    action = get_workflow_action(action_name)
    if action is None:
        return WorkflowActionResult(
            action_name=action_name,
            status="error",
            message=f"Workflow action is not registered: {action_name}.",
        )
    if action.requires_selected_job and not selected_job_id:
        return WorkflowActionResult(
            action_name=action.name,
            status="needs_input",
            message="Select a job before running this workflow action.",
            route_hint="Jobs",
            blockers=["Select a job before running this workflow action."],
        )

    try:
        return action.handler(base_dir, selected_job_id or "")
    except JobWorkflowServiceError as exc:
        message = str(exc)
        return WorkflowActionResult(
            action_name=action.name,
            status=_status_for_service_error(message),
            message=message,
            blockers=[message],
            route_hint=_route_for_error(message, action.route_hint),
            event_details={"error": message},
        )


def _discover_requirements(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    requirements = job_services.discover_application_requirements(base_dir, job_id)
    return WorkflowActionResult(
        action_name="discover_requirements",
        status="executed",
        message="Application requirements were saved for review.",
        route_hint="Jobs",
        event_details={
            "job_id": job_id,
            "review_status": requirements.review_status,
            "job_preserving": requirements.job_preserving,
        },
    )


def _review_requirements(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    requirements = load_application_requirements(base_dir, job_id)
    if requirements is None:
        raise JobWorkflowServiceError("Discover application requirements before review.")
    if requirements.status != "discovered" or not requirements.job_preserving:
        raise JobWorkflowServiceError(
            requirements.blocked_reason
            or "Resolve blocked application requirements before review."
        )
    reviewed = job_services.review_application_requirements(
        base_dir,
        job_id,
        **_requirements_review_fields(requirements),
    )
    return WorkflowActionResult(
        action_name="review_requirements",
        status="executed",
        message="Requirements review saved.",
        route_hint="Jobs",
        event_details={"job_id": job_id, "review_status": reviewed.review_status},
    )


def _generate_application_package(
    base_dir: Path | str,
    job_id: str,
) -> WorkflowActionResult:
    _package, json_path, markdown_path = job_services.generate_reviewable_application_package(
        base_dir,
        job_id,
    )
    return WorkflowActionResult(
        action_name="generate_application_package",
        status="executed",
        message="Application package saved for review.",
        route_hint="Jobs",
        artifact_paths=[str(json_path), str(markdown_path)],
    )


def _review_application_package(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    reviewed, json_path, markdown_path = job_services.review_application_package(
        base_dir,
        job_id,
        {},
    )
    return WorkflowActionResult(
        action_name="review_application_package",
        status="executed",
        message="Application package approved.",
        route_hint="Jobs",
        artifact_paths=[str(json_path), str(markdown_path)],
        event_details={"job_id": job_id, "status": reviewed.status},
    )


def _generate_fill_plan(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    fill_plan, saved_path = job_services.generate_reviewable_fill_plan(base_dir, job_id)
    return WorkflowActionResult(
        action_name="generate_fill_plan",
        status="executed",
        message="Application fill plan saved for review.",
        route_hint="Jobs",
        artifact_paths=[str(saved_path)],
        event_details={"job_id": job_id, "review_status": fill_plan.review_status},
    )


def _review_fill_plan(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    fill_plan = load_application_fill_plan(base_dir, job_id)
    if fill_plan is None:
        raise JobWorkflowServiceError("Generate an application fill plan before review.")
    submission = build_fill_plan_review_submission_from_defaults(fill_plan)
    reviewed = job_services.review_fill_plan(base_dir, job_id, **submission)
    return WorkflowActionResult(
        action_name="review_fill_plan",
        status="executed",
        message="Fill plan review saved.",
        route_hint="Jobs",
        event_details={"job_id": job_id, "review_status": reviewed.review_status},
    )


def _prepare_apply_assistance(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    state = load_current_workflow_state(base_dir, job_id)
    blockers = list(state.current_blockers)
    if blockers:
        raise JobWorkflowServiceError(" ".join(blockers))
    return WorkflowActionResult(
        action_name="prepare_apply_assistance",
        status="executed",
        message="Apply assistance is ready.",
        route_hint="Jobs",
    )


def _launch_browser_use(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    result = job_services.launch_apply_assistance(base_dir, job_id, final_submit=False)
    return WorkflowActionResult(
        action_name="launch_browser_use",
        status="executed",
        message=f"Started Browser Use apply assistance for {result.url}.",
        route_hint="Jobs",
        artifact_paths=[str(result.log_path)],
        event_details={"job_id": job_id, "pid": result.pid, "url": result.url},
    )


def _prepare_manual_application(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    state = load_current_workflow_state(base_dir, job_id)
    if state.current_blockers:
        raise JobWorkflowServiceError(" ".join(state.current_blockers))
    return WorkflowActionResult(
        action_name="prepare_manual_application",
        status="done",
        message="The job is prepared for manual application.",
        route_hint="Jobs",
    )


def _stop_browser_use_session(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    stopped = job_services.stop_active_browser_session(base_dir)
    return WorkflowActionResult(
        action_name="stop_browser_use_session",
        status="executed",
        message=(
            "Stopped the active Browser Use session."
            if stopped
            else "No active Browser Use session was found."
        ),
        event_details={"job_id": job_id, "stopped": stopped},
    )


def _kill_browser_use_processes(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    stopped_count = job_services.kill_browser_processes(base_dir)
    return WorkflowActionResult(
        action_name="kill_browser_use_processes",
        status="executed",
        message=f"Killed {stopped_count} Browser Use process group(s).",
        event_details={"job_id": job_id, "stopped_count": stopped_count},
    )


def _archive_job(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    job_services.archive_job(base_dir, job_id)
    return WorkflowActionResult(
        action_name="archive_job",
        status="executed",
        message="Job archived.",
        route_hint="Tracker",
        event_details={"job_id": job_id},
    )


def _restore_job(base_dir: Path | str, job_id: str) -> WorkflowActionResult:
    job_services.restore_job(base_dir, job_id)
    return WorkflowActionResult(
        action_name="restore_job",
        status="executed",
        message="Job restored.",
        route_hint="Tracker",
        event_details={"job_id": job_id},
    )


WORKFLOW_ACTION_REGISTRY = {
    "discover_requirements": WorkflowAction(
        name="discover_requirements",
        label="Discover application requirements",
        handler=_discover_requirements,
        permission_level=PermissionLevel.DRAFT_ONLY,
        route_hint="Jobs",
    ),
    "review_requirements": WorkflowAction(
        name="review_requirements",
        label="Review application requirements",
        handler=_review_requirements,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        review_gate=True,
        route_hint="Jobs",
    ),
    "generate_application_package": WorkflowAction(
        name="generate_application_package",
        label="Generate application package",
        handler=_generate_application_package,
        permission_level=PermissionLevel.DRAFT_ONLY,
        route_hint="Jobs",
    ),
    "review_application_package": WorkflowAction(
        name="review_application_package",
        label="Approve application package",
        handler=_review_application_package,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        review_gate=True,
        route_hint="Jobs",
    ),
    "generate_fill_plan": WorkflowAction(
        name="generate_fill_plan",
        label="Generate fill plan",
        handler=_generate_fill_plan,
        permission_level=PermissionLevel.DRAFT_ONLY,
        route_hint="Jobs",
    ),
    "review_fill_plan": WorkflowAction(
        name="review_fill_plan",
        label="Review fill plan",
        handler=_review_fill_plan,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        review_gate=True,
        route_hint="Jobs",
    ),
    "prepare_apply_assistance": WorkflowAction(
        name="prepare_apply_assistance",
        label="Prepare apply assistance",
        handler=_prepare_apply_assistance,
        permission_level=PermissionLevel.READ_ONLY,
        route_hint="Jobs",
    ),
    "launch_browser_use": WorkflowAction(
        name="launch_browser_use",
        label="Launch Browser Use",
        handler=_launch_browser_use,
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        external_effect=True,
        route_hint="Jobs",
    ),
    "prepare_manual_application": WorkflowAction(
        name="prepare_manual_application",
        label="Prepare manual application",
        handler=_prepare_manual_application,
        permission_level=PermissionLevel.READ_ONLY,
        route_hint="Jobs",
    ),
    "stop_browser_use_session": WorkflowAction(
        name="stop_browser_use_session",
        label="Stop Browser Use session",
        handler=_stop_browser_use_session,
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        external_effect=True,
    ),
    "kill_browser_use_processes": WorkflowAction(
        name="kill_browser_use_processes",
        label="Kill Browser Use processes",
        handler=_kill_browser_use_processes,
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        external_effect=True,
    ),
    "archive_job": WorkflowAction(
        name="archive_job",
        label="Archive job",
        handler=_archive_job,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        route_hint="Tracker",
    ),
    "restore_job": WorkflowAction(
        name="restore_job",
        label="Restore job",
        handler=_restore_job,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        route_hint="Tracker",
    ),
}


def _requirements_review_fields(requirements) -> dict[str, object]:
    return {
        "job_preserving": requirements.job_preserving,
        "confidence": requirements.confidence,
        "blocked_reason": requirements.blocked_reason or "",
        "required_documents_text": _format_findings(requirements.required_documents),
        "upload_expectations_text": _format_findings(requirements.upload_expectations),
        "motivation_label": (
            requirements.motivation_letter.label
            if requirements.motivation_letter is not None
            else ""
        ),
        "motivation_required": (
            requirements.motivation_letter.required
            if requirements.motivation_letter is not None
            else False
        ),
        "profile_fields_text": _format_form_fields(requirements.profile_fields),
        "screening_questions_text": _format_screening_questions(
            requirements.screening_questions
        ),
        "custom_form_fields_text": _format_form_fields(requirements.custom_form_fields),
        "consent_requirements_text": _format_findings(requirements.consent_requirements),
        "privacy_login_ats_gates_text": _format_findings(
            requirements.privacy_login_ats_gates
        ),
        "deadlines_text": _format_findings(requirements.deadlines),
        "contact_or_fallback_text": _format_findings(requirements.contact_or_fallback),
        "missing_or_uncertain_text": "\n".join(
            f"- {item}" for item in requirements.missing_or_uncertain
        ),
    }


def _format_findings(items: list[ApplicationRequirementFinding]) -> str:
    return "\n".join(
        f"- [{'required' if item.required else 'optional'}] {item.label}"
        for item in items
    )


def _format_form_fields(items: list[ApplicationFormField]) -> str:
    lines = []
    for item in items:
        suffix = f" | {item.input_type or 'text'}"
        if item.options:
            suffix += " | " + "; ".join(item.options)
        lines.append(
            f"- [{'required' if item.required else 'optional'}] {item.label}{suffix}"
        )
    return "\n".join(lines)


def _format_screening_questions(items: list[ApplicationScreeningQuestion]) -> str:
    return "\n".join(
        f"- [{'required' if item.required else 'optional'}] "
        f"{item.question} | {item.input_type or 'text'}"
        for item in items
    )


def _status_for_service_error(message: str) -> str:
    lowered = message.casefold()
    if (
        "provide" in lowered
        or "choose" in lowered
        or "open jobs" in lowered
        or "fields needing answers" in lowered
        or "blocked fields" in lowered
        or "upload" in lowered
    ):
        return "needs_input"
    return "blocked"


def _route_for_error(message: str, default_route: str | None) -> str | None:
    lowered = message.casefold()
    if "candidate profile" in lowered or "gender" in lowered or "upload cv" in lowered:
        return "Candidate Profile"
    if "apply url" in lowered or "normalized job" in lowered:
        return "Job Intake"
    if "tracker" in lowered or "archived" in lowered:
        return "Tracker"
    return default_route or "Jobs"
