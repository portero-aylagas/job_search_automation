"""Karen tool registry and implementations over the existing workflow APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.agent_chat import (
    ACTION_LABELS,
    get_or_create_agent_session,
    load_agent_chat_messages,
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
from src.application_package import load_application_package
from src.candidate_profile import validate_candidate_profile

PAGE_NAMES = ("Candidate Profile", "Job Intake", "Jobs", "Tracker", "Agent")


@dataclass(frozen=True)
class KarenToolDefinition:
    """Metadata for one callable Karen tool."""

    name: str
    permission_level: PermissionLevel
    description: str
    workflow_action: str | None = None
    route_page: str | None = None
    needs_job: bool = False


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
    ),
    "discover_requirements": KarenToolDefinition(
        name="discover_requirements",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Discover application requirements from the reviewed apply URL.",
        workflow_action="discover_requirements",
        needs_job=True,
    ),
    "generate_application_package": KarenToolDefinition(
        name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        description="Generate a draft application package.",
        workflow_action="generate_package",
        needs_job=True,
    ),
    "generate_fill_plan": KarenToolDefinition(
        name="generate_fill_plan",
        permission_level=PermissionLevel.DRAFT_ONLY,
        description="Generate a draft Browser Use fill plan.",
        workflow_action="generate_fill_plan",
        needs_job=True,
    ),
    "prepare_apply_assistance": KarenToolDefinition(
        name="prepare_apply_assistance",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        description="Check whether apply assistance is ready to launch from Jobs.",
        workflow_action="prepare_apply_assistance",
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
        description="Route to the expanded Karen dashboard.",
        route_page="Agent",
    ),
}

REVIEW_GATE_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        description="Review-gate action that must be handled in the Jobs review panels.",
    )
    for name in (
        "review_requirements",
        "approve_package",
        "reject_package",
        "review_fill_plan",
        "launch_browser_use",
    )
}

BLOCKED_TOOLS = {
    name: KarenToolDefinition(
        name=name,
        permission_level=PermissionLevel.FINAL_SUBMISSION,
        description="Blocked unsafe action.",
    )
    for name in (
        "final_submission",
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
                "Select a job on the Jobs page or Agent page before asking Karen "
                "to run a job-scoped workflow action."
            ),
            route_hint="Jobs",
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

    return _execute_read_only_tool(base_dir, context, definition, active_job_id=active_job_id)


def _execute_workflow_tool(
    base_dir: Path | str,
    context: KarenContext,
    definition: KarenToolDefinition,
    *,
    active_job_id: str | None,
    dependencies: AgentWorkflowDependencies | None,
) -> KarenToolResult:
    state = run_agent_workflow(
        base_dir,
        session_id=context.session_id,
        selected_job_id=active_job_id,
        action=definition.workflow_action or "status",
        dependencies=dependencies,
    )
    if state.errors:
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
            "run safe draft workflow steps after you explicitly ask. I cannot submit "
            "applications, automate login or captchas, message recruiters, approve "
            "review gates from chat, or invent candidate data."
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
        summary[status] = int(summary.get(status, 0)) + 1
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
        return "No job is selected. Select one on the Jobs page or Agent page."

    job = load_normalized_job(base_dir, job_id)
    if job is None:
        return "The selected job does not have reviewed intake data yet."

    requirements = load_application_requirements(base_dir, job_id)
    package = load_application_package(base_dir, job_id)
    fill_plan = load_application_fill_plan(base_dir, job_id)
    pieces = [
        f"{job.company} / {job.title}",
        f"Apply URL: {'present' if job.apply_url else 'missing'}",
        f"Requirements: {requirements.review_status if requirements else 'missing'}",
        f"Package: {package.status if package else 'missing'}",
        f"Fill plan: {fill_plan.review_status if fill_plan else 'missing'}",
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
