"""Karen tool registry and implementations over the existing workflow APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.agent_chat import (
    ACTION_LABELS,
    get_or_create_agent_session,
    load_agent_chat_messages,
    load_agent_events,
)
from src.agent_workflow import AgentWorkflowDependencies, run_agent_workflow
from src.agents.karen.policy import PermissionLevel
from src.agents.karen.state import KarenContext, KarenToolResult
from src.app_workflow import (
    load_application_requirements,
    load_candidate_profile,
    load_jobs_index,
    load_normalized_job,
)
from src.application_fill_plan import load_application_fill_plan
from src.application_fill_plan_review import build_fill_plan_review_submission_from_defaults
from src.application_package import load_application_package
from src.candidate_profile import validate_candidate_profile
from src.schemas import (
    ApplicationFormField,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
)
from src.services.candidate_profile_service import (
    CandidateProfileServiceError,
    save_candidate_preferences,
    save_candidate_review_fields,
    save_reviewed_candidate_profile,
)
from src.services.job_workflow_service import (
    JobWorkflowServiceError,
    archive_job,
    delete_job_data,
    kill_browser_processes,
    launch_apply_assistance,
    restore_job,
    review_application_package,
    review_application_requirements,
    review_fill_plan,
    run_karen_workflow_action,
    stop_active_browser_session,
)
from src.services.karen_permission_service import (
    grant_job_session_permission as service_grant_job_session_permission,
)
from src.services.karen_permission_service import (
    inspect_job_session_permission as service_inspect_job_session_permission,
)
from src.services.karen_permission_service import (
    revoke_job_session_permission as service_revoke_job_session_permission,
)
from src.tracker_status import tracker_status_label

AGENT_PAGE_NAME = "Agent Karen"
PAGE_NAMES = ("Candidate Profile", "Job Intake", "Jobs", "Tracker", AGENT_PAGE_NAME, "Agent")


@dataclass(frozen=True)
class KarenToolDefinition:
    """Metadata for one callable Karen tool."""

    name: str
    permission_level: PermissionLevel
    description: str
    workflow_action: str | None = None
    route_page: str | None = None
    needs_job: bool = False
    needs_permission: bool = False


READ_ONLY_TOOLS = {
    "explain_app": KarenToolDefinition(
        name="explain_app",
        permission_level=PermissionLevel.READ_ONLY,
        description="Explain the product workflow.",
    ),
    "explain_karen": KarenToolDefinition(
        name="explain_karen",
        permission_level=PermissionLevel.READ_ONLY,
        description="Explain Karen's role and boundaries.",
    ),
    "inspect_profile_status": KarenToolDefinition(
        name="inspect_profile_status",
        permission_level=PermissionLevel.READ_ONLY,
        description="Inspect candidate profile completeness.",
    ),
    "inspect_selected_job": KarenToolDefinition(
        name="inspect_selected_job",
        permission_level=PermissionLevel.READ_ONLY,
        description="Inspect selected job state.",
        needs_job=True,
    ),
    "list_blockers": KarenToolDefinition(
        name="list_blockers",
        permission_level=PermissionLevel.READ_ONLY,
        description="List current workflow blockers.",
    ),
    "list_next_actions": KarenToolDefinition(
        name="list_next_actions",
        permission_level=PermissionLevel.READ_ONLY,
        description="List next allowed actions.",
    ),
    "summarize_tracker": KarenToolDefinition(
        name="summarize_tracker",
        permission_level=PermissionLevel.READ_ONLY,
        description="Summarize tracker records.",
    ),
}

WORKFLOW_TOOLS = {
    "continue_workflow_until_next_gate": KarenToolDefinition(
        name="continue_workflow_until_next_gate",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Run safe workflow steps until the next human gate.",
        workflow_action="continue",
        needs_job=True,
        needs_permission=True,
    ),
    "continue_to_apply_assistance": KarenToolDefinition(
        name="continue_to_apply_assistance",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Run granted local workflow steps and launch fill-only Browser Use.",
        workflow_action="continue_to_apply_assistance",
        needs_job=True,
        needs_permission=True,
    ),
    "discover_requirements": KarenToolDefinition(
        name="discover_requirements",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Discover application requirements from the reviewed apply URL.",
        workflow_action="discover_requirements",
        needs_job=True,
        needs_permission=True,
    ),
    "generate_application_package": KarenToolDefinition(
        name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        description="Generate a draft application package.",
        workflow_action="generate_package",
        needs_job=True,
        needs_permission=True,
    ),
    "generate_fill_plan": KarenToolDefinition(
        name="generate_fill_plan",
        permission_level=PermissionLevel.DRAFT_ONLY,
        description="Generate a draft Browser Use fill plan.",
        workflow_action="generate_fill_plan",
        needs_job=True,
        needs_permission=True,
    ),
    "prepare_apply_assistance": KarenToolDefinition(
        name="prepare_apply_assistance",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        description="Check whether apply assistance is ready to launch from Jobs.",
        workflow_action="prepare_apply_assistance",
        needs_job=True,
        needs_permission=True,
    ),
    "launch_browser_use": KarenToolDefinition(
        name="launch_browser_use",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        description="Launch fill-only Browser Use apply assistance.",
        needs_job=True,
        needs_permission=True,
    ),
    "final_submission": KarenToolDefinition(
        name="final_submission",
        permission_level=PermissionLevel.FINAL_SUBMISSION,
        description="Launch final-submit Browser Use mode for a reviewed job.",
        needs_job=True,
        needs_permission=True,
    ),
    "stop_browser_use_session": KarenToolDefinition(
        name="stop_browser_use_session",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        description="Stop the active Browser Use session.",
        needs_job=True,
        needs_permission=True,
    ),
    "kill_browser_use_processes": KarenToolDefinition(
        name="kill_browser_use_processes",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        description="Kill Browser Use process groups started by this app.",
        needs_job=True,
        needs_permission=True,
    ),
    "archive_job": KarenToolDefinition(
        name="archive_job",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Archive one selected job.",
        needs_job=True,
        needs_permission=True,
    ),
    "restore_job": KarenToolDefinition(
        name="restore_job",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Restore one selected archived job.",
        needs_job=True,
        needs_permission=True,
    ),
    "update_tracker_status": KarenToolDefinition(
        name="update_tracker_status",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Tracker when a concrete status value is needed.",
        needs_job=True,
        needs_permission=True,
    ),
    "export_cover_letter": KarenToolDefinition(
        name="export_cover_letter",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Jobs when an export destination folder is needed.",
        needs_job=True,
        needs_permission=True,
    ),
    "delete_job_data": KarenToolDefinition(
        name="delete_job_data",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Permanently delete one selected job's local data.",
        needs_job=True,
        needs_permission=True,
    ),
}

PROFILE_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Candidate Profile action that needs uploaded files or reviewed form data.",
        route_page="Candidate Profile",
    )
    for name in (
        "parse_uploaded_cv",
        "parse_optional_document",
        "save_candidate_review_fields",
        "save_candidate_preferences",
        "save_reviewed_candidate_profile",
        "delete_candidate_document",
    )
}

JOB_INTAKE_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Job Intake action that needs URL or reviewed form data.",
        route_page="Job Intake",
    )
    for name in (
        "extract_job_url",
        "save_reviewed_job",
    )
}

PERMISSION_TOOLS = {
    "grant_job_session_permission": KarenToolDefinition(
        name="grant_job_session_permission",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Grant Karen full permission for the selected job in this session.",
        needs_job=True,
    ),
    "revoke_job_session_permission": KarenToolDefinition(
        name="revoke_job_session_permission",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Revoke Karen permissions for the selected job in this session.",
        needs_job=True,
    ),
    "inspect_job_session_permission": KarenToolDefinition(
        name="inspect_job_session_permission",
        permission_level=PermissionLevel.READ_ONLY,
        description="Inspect Karen permissions for the selected job in this session.",
        needs_job=True,
    ),
}

ROUTE_TOOLS = {
    "go_to_candidate_profile": KarenToolDefinition(
        name="go_to_candidate_profile",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Candidate Profile.",
        route_page="Candidate Profile",
    ),
    "go_to_job_intake": KarenToolDefinition(
        name="go_to_job_intake",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Job Intake.",
        route_page="Job Intake",
    ),
    "go_to_jobs": KarenToolDefinition(
        name="go_to_jobs",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Jobs.",
        route_page="Jobs",
    ),
    "go_to_tracker": KarenToolDefinition(
        name="go_to_tracker",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Tracker.",
        route_page="Tracker",
    ),
    "go_to_agent": KarenToolDefinition(
        name="go_to_agent",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Route to Karen's Agent tab.",
        route_page=AGENT_PAGE_NAME,
    ),
}

REVIEW_GATE_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Review a saved complete workflow artifact.",
        needs_job=True,
        needs_permission=True,
    )
    for name in (
        "review_requirements",
        "approve_package",
        "review_fill_plan",
    )
}

REVIEW_GATE_TOOLS["reject_package"] = KarenToolDefinition(
    name="reject_package",
    permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
    description="Package rejection must be handled in the Jobs review panel.",
    needs_job=True,
    needs_permission=True,
)

BLOCKED_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.FINAL_SUBMISSION,
        description="Blocked unsafe action.",
    )
    for name in (
        "login_automation",
        "captcha_handling",
        "recruiter_messaging",
        "bypass_review_gates",
        "invent_candidate_data",
    )
}

KAREN_TOOL_REGISTRY = {
    **READ_ONLY_TOOLS,
    **WORKFLOW_TOOLS,
    **PROFILE_TOOLS,
    **JOB_INTAKE_TOOLS,
    **PERMISSION_TOOLS,
    **ROUTE_TOOLS,
    **REVIEW_GATE_TOOLS,
    **BLOCKED_TOOLS,
}


def get_karen_tool_definition(tool_name: str | None) -> KarenToolDefinition | None:
    """Return registered metadata for a Karen tool name."""

    if not tool_name:
        return None
    return KAREN_TOOL_REGISTRY.get(tool_name)


def build_karen_context(
    base_dir: Path | str,
    *,
    current_page: str,
    selected_job_id: str | None,
    session_id: str | None = None,
    dependencies: AgentWorkflowDependencies | None = None,
) -> KarenContext:
    """Build Karen's read-only context from current persisted workflow state."""

    base_path = Path(base_dir)
    session = get_or_create_agent_session(
        base_path,
        session_id,
        selected_job_id=selected_job_id,
    )
    active_job_id = selected_job_id or session.selected_job_id
    workflow_state = run_agent_workflow(
        base_path,
        session_id=session.session_id,
        selected_job_id=active_job_id,
        dependencies=dependencies,
    )
    profile = load_candidate_profile(base_path)
    tracker_records = load_jobs_index(base_path)
    recent_messages = load_agent_chat_messages(base_path, session.session_id)[-8:]
    return KarenContext(
        session_id=session.session_id,
        current_page=current_page,
        selected_job_id=active_job_id,
        profile_status_summary=_profile_status_summary(profile),
        tracker_summary=_tracker_summary(tracker_records),
        artifact_presence=workflow_state.artifacts_present,
        blockers=workflow_state.blockers,
        pending_gate=workflow_state.pending_gate,
        next_allowed_actions=workflow_state.next_allowed_actions,
        recent_transcript_summary=_recent_transcript_summary(recent_messages),
        job_permissions=session.job_permissions,
    )


def execute_karen_tool(
    base_dir: Path | str,
    context: KarenContext,
    tool_name: str,
    *,
    target_job_id: str | None = None,
    route_page: str | None = None,
    dependencies: AgentWorkflowDependencies | None = None,
) -> KarenToolResult:
    """Execute one approved Karen tool."""

    definition = get_karen_tool_definition(tool_name)
    if definition is None:
        return KarenToolResult(
            tool_name=tool_name,
            status="error",
            message=f"Karen does not have a registered tool named {tool_name}.",
        )

    active_job_id = target_job_id or context.selected_job_id
    if definition.needs_job and not active_job_id:
        return KarenToolResult(
            tool_name=tool_name,
            status="needs_job",
            message=(
                "Select a job on the Jobs page or Agent Karen tab before asking Karen "
                "to run a job-scoped workflow action."
            ),
            route_hint="Jobs",
        )

    if definition.name in {
        "grant_job_session_permission",
        "revoke_job_session_permission",
        "inspect_job_session_permission",
    }:
        return _execute_permission_tool(
            base_dir,
            context,
            definition,
            active_job_id=active_job_id,
        )

    permission_result = _check_execution_permission(context, definition, active_job_id)
    if permission_result is not None:
        return permission_result

    if definition.name in PROFILE_TOOLS:
        return _execute_profile_tool(base_dir, definition)

    if definition.name in JOB_INTAKE_TOOLS:
        page = definition.route_page or "Jobs"
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_input",
            message=(
                f"Open {page} to provide the required file upload, URL, or "
                "reviewed form fields for this action."
            ),
            route_hint=page,
        )

    if definition.route_page:
        page = route_page or definition.route_page
        if page not in PAGE_NAMES:
            page = definition.route_page
        return KarenToolResult(
            tool_name=tool_name,
            status="routed",
            message=f"Opening {page}.",
            route_hint=page,
            event_details={"route_page": page},
        )

    if definition.workflow_action:
        return _execute_workflow_tool(
            base_dir,
            context,
            definition,
            active_job_id=active_job_id,
            dependencies=dependencies,
        )

    if definition.name == "delete_job_data":
        return _execute_delete_job_tool(base_dir, definition, active_job_id=active_job_id)

    if definition.name in {
        "archive_job",
        "restore_job",
        "update_tracker_status",
        "export_cover_letter",
        "launch_browser_use",
        "final_submission",
        "stop_browser_use_session",
        "kill_browser_use_processes",
    }:
        return _execute_service_tool(base_dir, definition, active_job_id=active_job_id)

    if definition.name in REVIEW_GATE_TOOLS:
        return _execute_review_gate_tool(
            base_dir,
            definition,
            active_job_id=active_job_id,
        )

    return _execute_read_only_tool(base_dir, context, definition, active_job_id=active_job_id)


def _execute_profile_tool(
    base_dir: Path | str,
    definition: KarenToolDefinition,
) -> KarenToolResult:
    if definition.name in {
        "parse_uploaded_cv",
        "parse_optional_document",
        "delete_candidate_document",
    }:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_input",
            message=(
                "Open Candidate Profile to provide the required file upload or "
                "document selection for this action."
            ),
            route_hint="Candidate Profile",
        )

    profile = load_candidate_profile(base_dir)
    try:
        if definition.name == "save_candidate_review_fields":
            saved = save_candidate_review_fields(base_dir, profile)
            message = "Saved the current candidate review fields."
        elif definition.name == "save_candidate_preferences":
            saved = save_candidate_preferences(base_dir, profile)
            message = "Saved the current candidate preferences."
        elif definition.name == "save_reviewed_candidate_profile":
            saved = save_reviewed_candidate_profile(base_dir, profile)
            message = "Saved the reviewed candidate profile."
        else:
            saved = profile
            message = "Open Candidate Profile to complete this action."
    except CandidateProfileServiceError as exc:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_input",
            message=str(exc),
            route_hint="Candidate Profile",
            event_details={"error": str(exc)},
        )

    return KarenToolResult(
        tool_name=definition.name,
        status="executed",
        message=message,
        event_details={
            "profile_complete": not validate_candidate_profile(saved),
        },
    )


def _execute_permission_tool(
    base_dir: Path | str,
    context: KarenContext,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
) -> KarenToolResult:
    if not active_job_id:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_job",
            message="Select a job before changing Karen session permissions.",
            route_hint="Jobs",
        )
    if definition.name == "grant_job_session_permission":
        session = service_grant_job_session_permission(
            base_dir,
            session_id=context.session_id,
            job_id=active_job_id,
            allow_app_mutations=True,
            allow_browser_launch=True,
            allow_final_submission=True,
        )
        grant = session.job_permissions[active_job_id]
        return KarenToolResult(
            tool_name=definition.name,
            status="executed",
            message=(
                "Granted Karen app mutations, Browser Use launch, and final "
                f"submission for job {active_job_id} in this session."
            ),
            event_details={"job_id": active_job_id, **grant.model_dump(mode="json")},
        )
    if definition.name == "revoke_job_session_permission":
        service_revoke_job_session_permission(
            base_dir,
            session_id=context.session_id,
            job_id=active_job_id,
        )
        return KarenToolResult(
            tool_name=definition.name,
            status="executed",
            message=f"Revoked Karen permissions for job {active_job_id}.",
            event_details={"job_id": active_job_id},
        )

    grant = service_inspect_job_session_permission(
        base_dir,
        session_id=context.session_id,
        job_id=active_job_id,
    )
    return KarenToolResult(
        tool_name=definition.name,
        status="answered",
        message=(
            f"Permissions for job {active_job_id}: app mutations="
            f"{grant.allow_app_mutations}, Browser Use launch="
            f"{grant.allow_browser_launch}, final submission="
            f"{grant.allow_final_submission}."
        ),
        event_details={"job_id": active_job_id, **grant.model_dump(mode="json")},
    )


def _check_execution_permission(
    context: KarenContext,
    definition: KarenToolDefinition,
    active_job_id: str | None,
) -> KarenToolResult | None:
    if not definition.needs_permission:
        return None
    if not active_job_id:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_job",
            message="Select a job before running this job-scoped action.",
            route_hint="Jobs",
        )
    grant = context.job_permissions.get(active_job_id)
    if grant is None:
        return KarenToolResult(
            tool_name=definition.name,
            status="refused",
            message=(
                "This job-scoped action requires a per-job Karen session grant."
            ),
            route_hint="Agent Karen",
        )
    if definition.name == "continue_to_apply_assistance" and not (
        grant.allow_app_mutations and grant.allow_browser_launch
    ):
        return KarenToolResult(
            tool_name=definition.name,
            status="refused",
            message=(
                "This action requires app mutation and Browser Use launch permission "
                "for the selected job."
            ),
        )
    if definition.permission_level in {
        PermissionLevel.DRAFT_ONLY,
        PermissionLevel.MUTATES_LOCAL_STATE,
    } and not grant.allow_app_mutations:
        return KarenToolResult(
            tool_name=definition.name,
            status="refused",
            message="This action requires app mutation permission for the selected job.",
        )
    if (
        definition.permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION
        and not grant.allow_browser_launch
    ):
        return KarenToolResult(
            tool_name=definition.name,
            status="refused",
            message="This action requires Browser Use launch permission for the selected job.",
        )
    if (
        definition.permission_level == PermissionLevel.FINAL_SUBMISSION
        and not grant.allow_final_submission
    ):
        return KarenToolResult(
            tool_name=definition.name,
            status="refused",
            message="This action requires final submission permission for the selected job.",
        )
    return None


def _execute_review_gate_tool(
    base_dir: Path | str,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
) -> KarenToolResult:
    if not active_job_id:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_job",
            message="Select a job before reviewing workflow artifacts.",
            route_hint="Jobs",
        )

    try:
        if definition.name == "review_requirements":
            requirements = load_application_requirements(base_dir, active_job_id)
            if requirements is None:
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message="Discover application requirements before reviewing them.",
                    route_hint="Jobs",
                )
            if requirements.status != "discovered" or not requirements.job_preserving:
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message=(
                        "Open Jobs to resolve the blocked or non-job-preserving "
                        "application requirements."
                    ),
                    route_hint="Jobs",
                    event_details={
                        "job_id": active_job_id,
                        "status": requirements.status,
                        "job_preserving": requirements.job_preserving,
                    },
                )
            reviewed = review_application_requirements(
                base_dir,
                active_job_id,
                **_requirements_review_fields(requirements),
            )
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message="Requirements review saved.",
                event_details={
                    "job_id": active_job_id,
                    "review_status": reviewed.review_status,
                },
            )

        if definition.name == "approve_package":
            package = load_application_package(base_dir, active_job_id)
            if package is None:
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message="Generate an application package before approving it.",
                    route_hint="Jobs",
                )
            if package.status == "rejected":
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message=(
                        "Open Jobs to regenerate or manually edit the rejected "
                        "application package before approval."
                    ),
                    route_hint="Jobs",
                    event_details={"job_id": active_job_id, "status": package.status},
                )
            reviewed, json_path, markdown_path = review_application_package(
                base_dir,
                active_job_id,
                {},
            )
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message="Application package approved.",
                artifact_paths=[str(json_path), str(markdown_path)],
                event_details={
                    "job_id": active_job_id,
                    "status": reviewed.status,
                },
            )

        if definition.name == "review_fill_plan":
            fill_plan = load_application_fill_plan(base_dir, active_job_id)
            if fill_plan is None:
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message="Generate an application fill plan before reviewing it.",
                    route_hint="Jobs",
                )
            submission = build_fill_plan_review_submission_from_defaults(fill_plan)
            reviewed = review_fill_plan(base_dir, active_job_id, **submission)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message="Fill plan review saved.",
                event_details={
                    "job_id": active_job_id,
                    "review_status": reviewed.review_status,
                },
            )
    except JobWorkflowServiceError as exc:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_input",
            message=_review_gate_input_message(definition.name, str(exc)),
            route_hint="Jobs",
            event_details={"job_id": active_job_id, "error": str(exc)},
        )

    return KarenToolResult(
        tool_name=definition.name,
        status="error",
        message=f"Karen does not have an implementation for {definition.name}.",
    )


def _review_gate_input_message(tool_name: str, error: str) -> str:
    if tool_name == "review_fill_plan":
        if "fields needing answers" in error:
            return (
                "Open Jobs to provide reviewed values for fields needing answers "
                "before Karen can save the fill-plan review."
            )
        if "previously blocked fields" in error:
            return (
                "Open Jobs to resolve blocked fill-plan fields before Karen can "
                "save the fill-plan review."
            )
        if "Provide values for required fields" in error:
            return (
                "Open Jobs to provide reviewed values for required fill-plan fields "
                "before Karen can save the fill-plan review."
            )
        if (
            "required uploads" in error
            or "file paths" in error
            or "reviewed source file" in error
            or "source-file metadata is missing" in error
        ):
            return (
                "Open Jobs to choose required upload file paths before Karen can "
                "save the fill-plan review."
            )
    return error


def _requirements_review_fields(requirements: ApplicationRequirements) -> dict[str, object]:
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


def _execute_delete_job_tool(
    base_dir: Path | str,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
) -> KarenToolResult:
    if not active_job_id:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_job",
            message="Select a job before asking Karen to delete job data.",
            route_hint="Jobs",
        )
    tracker_record = next(
        (record for record in load_jobs_index(base_dir) if record.job_id == active_job_id),
        None,
    )
    if tracker_record is None:
        return KarenToolResult(
            tool_name=definition.name,
            status="error",
            message=f"Karen could not find tracker data for job {active_job_id}.",
        )
    delete_job_data(base_dir, active_job_id)
    label = f"{tracker_record.company} / {tracker_record.title}"
    return KarenToolResult(
        tool_name=definition.name,
        status="executed",
        message=f"Deleted local data for {label}.",
        event_details={"deleted_job_id": active_job_id},
    )


def _execute_service_tool(
    base_dir: Path | str,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
) -> KarenToolResult:
    if not active_job_id:
        return KarenToolResult(
            tool_name=definition.name,
            status="needs_job",
            message="Select a job before running this action.",
            route_hint="Jobs",
        )
    try:
        if definition.name == "archive_job":
            record = archive_job(base_dir, active_job_id)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message="Job archived.",
                event_details={"job_id": active_job_id, "record": _dump_model(record)},
            )
        if definition.name == "restore_job":
            record = restore_job(base_dir, active_job_id)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message="Job restored.",
                event_details={"job_id": active_job_id, "record": _dump_model(record)},
            )
        if definition.name == "update_tracker_status":
            return KarenToolResult(
                tool_name=definition.name,
                status="needs_input",
                message=(
                    "Open Tracker to choose the exact status value to save for this job."
                ),
                route_hint="Tracker",
            )
        if definition.name == "export_cover_letter":
            return KarenToolResult(
                tool_name=definition.name,
                status="needs_input",
                message="Open Jobs to choose a destination folder for the cover letter export.",
                route_hint="Jobs",
            )
        if definition.name == "launch_browser_use":
            result = launch_apply_assistance(base_dir, active_job_id, final_submit=False)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message=f"Started Browser Use apply assistance for {result.url}.",
                artifact_paths=[str(result.log_path)],
                event_details={"job_id": active_job_id, "pid": result.pid},
            )
        if definition.name == "final_submission":
            result = launch_apply_assistance(base_dir, active_job_id, final_submit=True)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message=f"Started Browser Use final-submit mode for {result.url}.",
                artifact_paths=[str(result.log_path)],
                event_details={
                    "job_id": active_job_id,
                    "pid": result.pid,
                    "final_submit": True,
                },
            )
        if definition.name == "stop_browser_use_session":
            stopped = stop_active_browser_session(base_dir)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message=(
                    "Stopped the active Browser Use session."
                    if stopped
                    else "No active Browser Use session was found."
                ),
                event_details={"job_id": active_job_id, "stopped": stopped},
            )
        if definition.name == "kill_browser_use_processes":
            stopped_count = kill_browser_processes(base_dir)
            return KarenToolResult(
                tool_name=definition.name,
                status="executed",
                message=f"Killed {stopped_count} Browser Use process group(s).",
                event_details={"job_id": active_job_id, "stopped_count": stopped_count},
            )
    except JobWorkflowServiceError as exc:
        return KarenToolResult(
            tool_name=definition.name,
            status="error",
            message=str(exc),
            event_details={"job_id": active_job_id},
        )

    return KarenToolResult(
        tool_name=definition.name,
        status="error",
        message=f"Karen does not have an implementation for {definition.name}.",
    )


def _execute_workflow_tool(
    base_dir: Path | str,
    context: KarenContext,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
    dependencies: AgentWorkflowDependencies | None,
) -> KarenToolResult:
    state = run_karen_workflow_action(
        base_dir,
        session_id=context.session_id,
        selected_job_id=active_job_id,
        action=definition.workflow_action or "status",
        dependencies=dependencies,
    )
    if state.errors:
        if definition.name == "continue_to_apply_assistance":
            message = _continue_to_apply_input_message(state.errors[-1])
            if message:
                return KarenToolResult(
                    tool_name=definition.name,
                    status="needs_input",
                    message=message,
                    route_hint="Jobs",
                    event_details={"errors": state.errors},
                )
        return KarenToolResult(
            tool_name=definition.name,
            status="error",
            message=state.errors[-1],
            event_details={"errors": state.errors},
        )

    action_label = ACTION_LABELS.get(
        definition.workflow_action or "",
        definition.name.replace("_", " "),
    )
    message_parts = [f"{action_label} completed."]
    recent_events = load_agent_events(base_dir, context.session_id)
    if definition.name == "continue_to_apply_assistance" and (
        recent_events
        and recent_events[-1].action == "launch_browser_use"
        and recent_events[-1].result == "browser_use_started"
    ):
        message_parts = ["Browser Use started for apply assistance."]
    if state.pending_gate:
        message_parts.append(f"Next human gate: {state.pending_gate}.")
    if state.next_allowed_actions:
        readable_actions = [
            ACTION_LABELS.get(action, action.replace("_", " "))
            for action in state.next_allowed_actions
        ]
        message_parts.append("Next allowed actions: " + "; ".join(readable_actions) + ".")
    return KarenToolResult(
        tool_name=definition.name,
        status="executed",
        message=" ".join(message_parts),
        event_details={
            "workflow_action": definition.workflow_action or "",
            "pending_gate": state.pending_gate or "",
            "next_allowed_actions": state.next_allowed_actions,
        },
    )


def _continue_to_apply_input_message(error: str) -> str:
    """Return a user-facing next step for apply-assistance review blockers."""

    if "Save reviewed values for all fields needing answers." in error:
        return (
            "Browser Use cannot start yet. Open Jobs and review the application fill "
            "plan values for fields needing answers, then save the fill-plan review."
        )
    if "Save reviewed values for all previously blocked fields." in error:
        return (
            "Browser Use cannot start yet. Open Jobs and review the application fill "
            "plan values for previously blocked fields, then save the fill-plan review."
        )
    if "Review the application fill plan before applying." in error:
        return (
            "Browser Use cannot start yet. Open Jobs and save the application fill-plan "
            "review first."
        )
    if "Provide values for required fields" in error:
        return (
            "Browser Use cannot start yet. Open Jobs and provide reviewed values for "
            "required fill-plan fields, then save the fill-plan review."
        )
    if "required uploads" in error or "reviewed source file" in error:
        return (
            "Browser Use cannot start yet. Open Jobs and choose required upload file "
            "paths, then save the fill-plan review."
        )
    return ""


def _execute_read_only_tool(
    base_dir: Path | str,
    context: KarenContext,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
) -> KarenToolResult:
    if definition.name == "explain_app":
        message = (
            "This app turns a reviewed candidate profile and a reviewed job position "
            "into validated application material. The workflow is gated: profile, "
            "job intake, requirements, package, fill plan, and apply "
            "assistance each stay visible for human review."
        )
    elif definition.name == "explain_karen":
        message = (
            "I am Karen, the runtime assistant for this app. I can explain the "
            "workflow, inspect state, suggest next steps, route you to panels, and "
            "run workflow steps after you explicitly ask and grant per-job session "
            "permission. Final submission is available only for a granted selected "
            "job. I cannot automate login, MFA, captchas, account creation, "
            "recruiter messaging, or invent candidate data."
        )
    elif definition.name == "inspect_profile_status":
        message = context.profile_status_summary
    elif definition.name == "inspect_selected_job":
        message = _selected_job_summary(base_dir, active_job_id)
    elif definition.name == "list_blockers":
        message = _list_or_none("Current blockers", context.blockers)
    elif definition.name == "list_next_actions":
        readable_actions = [
            ACTION_LABELS.get(action, action.replace("_", " "))
            for action in context.next_allowed_actions
        ]
        message = _list_or_none("Next allowed actions", readable_actions)
    elif definition.name == "summarize_tracker":
        message = _format_tracker_summary(context.tracker_summary)
    else:
        message = definition.description

    return KarenToolResult(
        tool_name=definition.name,
        status="answered",
        message=message,
    )


def _profile_status_summary(profile: object) -> str:
    errors = validate_candidate_profile(profile)
    if not errors:
        return "Candidate profile is complete enough for the current workflow."
    return "Candidate profile is incomplete: " + "; ".join(errors) + "."


def _tracker_summary(tracker_records: list[object]) -> dict[str, int | str]:
    summary: dict[str, int | str] = {"total": len(tracker_records)}
    for record in tracker_records:
        status = getattr(record, "status", "unknown")
        label = tracker_status_label(status) if status != "unknown" else "Unknown"
        summary[label] = int(summary.get(label, 0)) + 1
    return summary


def _recent_transcript_summary(messages: list[object]) -> str:
    if not messages:
        return "No recent Karen transcript yet."
    lines = []
    for message in messages:
        role = getattr(message, "role", "message")
        content = str(getattr(message, "content", "")).replace("\n", " ").strip()
        if len(content) > 180:
            content = content[:177].rstrip() + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _selected_job_summary(base_dir: Path | str, job_id: str | None) -> str:
    if not job_id:
        return "No job is selected. Select one on the Jobs page or Agent Karen tab."

    job = load_normalized_job(base_dir, job_id)
    if job is None:
        return "The selected job does not have reviewed intake data yet."

    requirements = load_application_requirements(base_dir, job_id)
    package = load_application_package(base_dir, job_id)
    fill_plan = load_application_fill_plan(base_dir, job_id)
    tracker_record = next(
        (record for record in load_jobs_index(base_dir) if record.job_id == job_id),
        None,
    )
    tracker_status = (
        tracker_status_label(tracker_record.status) if tracker_record is not None else "missing"
    )
    pieces = [
        f"{job.company} / {job.title}",
        f"Application tracker status: {tracker_status}",
        f"Apply URL: {'present' if job.apply_url else 'missing'}",
        f"Requirements review: {requirements.review_status if requirements else 'missing'}",
        f"Package review: {package.status if package else 'missing'}",
        f"Fill plan review: {fill_plan.review_status if fill_plan else 'missing'}",
    ]
    return ". ".join(pieces) + "."


def _format_tracker_summary(summary: dict[str, int | str]) -> str:
    total = summary.get("total", 0)
    status_parts = [
        f"{key}: {value}" for key, value in summary.items() if key != "total"
    ]
    if not status_parts:
        return f"Tracker has {total} job records."
    return f"Tracker has {total} job records. Status counts: " + "; ".join(status_parts) + "."


def _list_or_none(label: str, items: list[str]) -> str:
    if not items:
        return f"{label}: none."
    return f"{label}: " + "; ".join(items) + "."


def _dump_model(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return None
