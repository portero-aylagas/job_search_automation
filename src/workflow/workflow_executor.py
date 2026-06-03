"""Bounded Karen workflow execution over registered shared actions.

Karen is permissioned to operate the same workflow controls as the user. The
executor runs only registered actions, reloads persisted workflow state after
each action, and reports backend blockers instead of bypassing them. It is not
an alternate source of workflow truth and does not own Browser Use behavior
after launch.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from src.agent_chat import (
    ACTION_LABELS,
    append_agent_chat_message,
    create_agent_run_id,
    log_agent_event,
)
from src.agents.karen.policy import PermissionLevel
from src.schemas import AgentChatMessage, AgentWorkflowEvent
from src.services.karen_permission_service import inspect_job_session_permission
from src.workflow.action_registry import (
    WORKFLOW_ACTION_REGISTRY,
    WorkflowActionResult,
    execute_registered_action,
    get_workflow_action,
)
from src.workflow.workflow_planner import WorkflowIntent, planner_next_action
from src.workflow.workflow_state import load_current_workflow_state

MAX_WORKFLOW_STEPS = 10


class WorkflowRunResult(BaseModel):
    """Public result from a Karen workflow-controller run."""

    status: str
    message: str
    blockers: list[str] = Field(default_factory=list)
    route_hint: str | None = None
    executed_actions: list[str] = Field(default_factory=list)
    pending_gate: str | None = None
    next_allowed_actions: list[str] = Field(default_factory=list)
    selected_job_id: str | None = None
    event_details: dict[str, object] = Field(default_factory=dict)
    artifact_paths: list[str] = Field(default_factory=list)


def run_karen_workflow_goal(
    base_dir: Path | str,
    *,
    session_id: str,
    selected_job_id: str | None,
    intent: WorkflowIntent,
    workflow_run_id: str | None = None,
) -> WorkflowRunResult:
    """Run a bounded deterministic workflow loop for one structured intent.

    Karen-specific code here is limited to permission checks, action dispatch,
    state reload, and result reporting. The underlying workflow services remain
    authoritative for validation, review gates, and blockers.
    """

    base_path = Path(base_dir)
    active_job_id = intent.target_job_id or selected_job_id
    executed_actions: list[str] = []
    artifact_paths: list[str] = []
    last_result: WorkflowActionResult | None = None
    workflow_run_id = workflow_run_id or create_agent_run_id()

    _log_workflow_intent(
        base_path,
        session_id=session_id,
        job_id=active_job_id,
        intent=intent,
        workflow_run_id=workflow_run_id,
    )

    for step_index in range(MAX_WORKFLOW_STEPS):
        state = load_current_workflow_state(base_path, active_job_id)
        decision = planner_next_action(state, intent)

        if decision.status == "action" and decision.action_name:
            policy_message = _policy_refusal(
                base_path,
                session_id=session_id,
                active_job_id=active_job_id,
                action_name=decision.action_name,
                intent=intent,
            )
            if policy_message:
                _log_workflow_refusal(
                    base_path,
                    session_id=session_id,
                    job_id=active_job_id,
                    action_name=decision.action_name,
                    workflow_run_id=workflow_run_id,
                    step_index=step_index,
                    message=policy_message,
                )
                return _result_from_state(
                    state,
                    status="refused",
                    message=policy_message,
                    executed_actions=executed_actions,
                )

            _log_workflow_action_started(
                base_path,
                session_id=session_id,
                job_id=active_job_id,
                action_name=decision.action_name,
                workflow_run_id=workflow_run_id,
                step_index=step_index,
                planner_message=decision.message,
            )
            previous_result = last_result
            action_result = execute_registered_action(
                decision.action_name,
                base_path,
                active_job_id,
            )
            last_result = action_result
            executed_actions.append(action_result.action_name)
            artifact_paths.extend(action_result.artifact_paths)
            _log_workflow_action(
                base_path,
                session_id=session_id,
                job_id=active_job_id,
                result=action_result,
                workflow_run_id=workflow_run_id,
                step_index=step_index,
                planner_message=decision.message,
            )
            if action_result.status not in {"executed", "done"}:
                refreshed = load_current_workflow_state(base_path, active_job_id)
                return _result_from_state(
                    refreshed,
                    status=action_result.status,
                    message=_message_for_action_failure(action_result, previous_result),
                    blockers=action_result.blockers,
                    route_hint=action_result.route_hint,
                    executed_actions=executed_actions,
                    artifact_paths=artifact_paths,
                    event_details=action_result.event_details,
                )
            if action_result.status == "done":
                refreshed = load_current_workflow_state(base_path, active_job_id)
                return _result_from_state(
                    refreshed,
                    status="done" if action_result.status == "executed" else action_result.status,
                    message=_message_for_terminal_action(action_result, previous_result),
                    route_hint=action_result.route_hint,
                    executed_actions=executed_actions,
                    artifact_paths=artifact_paths,
                    event_details=action_result.event_details,
                )
            continue

        _log_workflow_decision(
            base_path,
            session_id=session_id,
            job_id=active_job_id,
            workflow_run_id=workflow_run_id,
            status=decision.status,
            message=_message_for_stop(decision.message, last_result),
            blockers=decision.blockers,
            route_hint=decision.route_hint,
            next_allowed_actions=state.next_allowed_actions,
        )
        return _result_from_state(
            state,
            status=decision.status,
            message=_message_for_stop(decision.message, last_result),
            blockers=decision.blockers,
            route_hint=decision.route_hint,
            executed_actions=executed_actions,
            artifact_paths=artifact_paths,
        )

    state = load_current_workflow_state(base_path, active_job_id)
    _log_workflow_decision(
        base_path,
        session_id=session_id,
        job_id=active_job_id,
        workflow_run_id=workflow_run_id,
        status="blocked",
        message="Maximum Karen workflow steps reached.",
        blockers=["Maximum Karen workflow steps reached."],
        route_hint=state.route_hint,
        next_allowed_actions=state.next_allowed_actions,
    )
    return _result_from_state(
        state,
        status="blocked",
        message="Maximum Karen workflow steps reached.",
        blockers=["Maximum Karen workflow steps reached."],
        executed_actions=executed_actions,
        artifact_paths=artifact_paths,
    )


def _policy_refusal(
    base_dir: Path,
    *,
    session_id: str,
    active_job_id: str | None,
    action_name: str,
    intent: WorkflowIntent,
) -> str:
    action = get_workflow_action(action_name)
    if action is None:
        return f"Workflow action is not registered: {action_name}."
    grant = (
        inspect_job_session_permission(
            base_dir,
            session_id=session_id,
            job_id=active_job_id,
        )
        if active_job_id
        else None
    )
    if action.review_gate and not intent.allow_review_gate_crossing:
        return "Karen needs explicit review-gate permission before marking this artifact reviewed."
    if action.external_effect:
        if action.permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION:
            if action.name in {"stop_browser_use_session", "kill_browser_use_processes"}:
                if intent.allow_browser_launch or intent.allow_local_mutations:
                    if grant is not None and grant.allow_browser_launch:
                        return ""
            if not intent.allow_browser_launch or intent.execution_mode != "browser_use":
                return "Browser Use launch requires permission."
            if grant is None or not grant.allow_browser_launch:
                return (
                    "Karen needs a per-job session grant with Browser Use launch "
                    "permission before running this action."
                )
    if action.permission_level == PermissionLevel.DRAFT_ONLY and not (
        intent.allow_draft_generation or intent.allow_local_mutations
    ):
        return "Karen needs explicit draft-generation permission for this action."
    if action.permission_level == PermissionLevel.DRAFT_ONLY and (
        grant is None or not grant.allow_app_mutations
    ):
        return (
            "Karen needs a per-job session grant with app mutation permission "
            "before generating workflow artifacts."
        )
    if (
        action.permission_level == PermissionLevel.MUTATES_LOCAL_STATE
        and not intent.allow_local_mutations
        and not action.review_gate
    ):
        return "Karen needs explicit local workflow mutation permission for this action."
    if action.permission_level == PermissionLevel.MUTATES_LOCAL_STATE and (
        grant is None or not grant.allow_app_mutations
    ):
        return (
            "Karen needs a per-job session grant with app mutation permission "
            "before changing workflow state."
        )
    return ""


def _result_from_state(
    state,
    *,
    status: str,
    message: str,
    blockers: list[str] | None = None,
    route_hint: str | None = None,
    executed_actions: list[str],
    artifact_paths: list[str] | None = None,
    event_details: dict[str, object] | None = None,
) -> WorkflowRunResult:
    return WorkflowRunResult(
        status=status,
        message=message,
        blockers=blockers if blockers is not None else list(state.current_blockers),
        route_hint=route_hint or state.route_hint,
        executed_actions=list(executed_actions),
        pending_gate=state.pending_gate,
        next_allowed_actions=list(state.next_allowed_actions),
        selected_job_id=state.selected_job_id,
        artifact_paths=list(artifact_paths or []),
        event_details=dict(event_details or {}),
    )


def _message_for_stop(message: str, last_result: WorkflowActionResult | None) -> str:
    if last_result is None:
        return message
    if message.startswith("No further workflow action"):
        return last_result.message
    return message


def _message_for_terminal_action(
    action_result: WorkflowActionResult,
    previous_result: WorkflowActionResult | None,
) -> str:
    if (
        action_result.action_name == "launch_browser_use"
        and previous_result is not None
        and previous_result.action_name == "review_fill_plan"
    ):
        return f"{previous_result.message}\n\n{action_result.message}"
    return action_result.message


def _message_for_action_failure(
    action_result: WorkflowActionResult,
    previous_result: WorkflowActionResult | None,
) -> str:
    if (
        action_result.action_name == "launch_browser_use"
        and previous_result is not None
        and previous_result.action_name == "review_fill_plan"
    ):
        return (
            f"{previous_result.message}\n\n"
            "Tried to launch Browser Use, but the backend blocked it:\n"
            f"{action_result.message}"
        )
    return action_result.message


def _log_workflow_action(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    result: WorkflowActionResult,
    workflow_run_id: str,
    step_index: int,
    planner_message: str,
) -> None:
    details = dict(result.event_details)
    label = _action_label(result.action_name)
    progress_status = _progress_status_from_result(result.status)
    action = get_workflow_action(result.action_name)
    refresh_scopes = sorted(action.refresh_scopes) if action is not None else []
    metadata = dict(result.event_details)
    metadata["refresh_scopes"] = list(refresh_scopes)
    details.update(
        {
            "workflow_run_id": workflow_run_id,
            "step_index": step_index,
            "planner_message": planner_message,
            "action_label": label,
            "progress_status": progress_status,
            "event_type": "workflow_action",
            "refresh_scopes": list(refresh_scopes),
        }
    )
    event = AgentWorkflowEvent(
        event_type="workflow_action",
        session_id=session_id,
        job_id=job_id,
        run_id=workflow_run_id,
        action=result.action_name,
        label=label,
        result=result.status,
        status=progress_status,
        message=result.message,
        blockers=list(result.blockers),
        route_hint=result.route_hint,
        gate=None,
        artifact_paths=result.artifact_paths,
        refresh_scopes=list(refresh_scopes),
        metadata=metadata,
        details=details,
    )
    log_agent_event(base_dir, event)
    _append_progress_chat_message(base_dir, event)


def _log_workflow_refusal(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    action_name: str,
    workflow_run_id: str,
    step_index: int,
    message: str,
) -> None:
    label = _action_label(action_name)
    event = AgentWorkflowEvent(
        event_type="workflow_action",
        session_id=session_id,
        job_id=job_id,
        run_id=workflow_run_id,
        action=action_name,
        label=label,
        result="refused",
        status="refused",
        message=message,
        blockers=[message],
        route_hint="Jobs",
        details={
            "workflow_run_id": workflow_run_id,
            "step_index": step_index,
            "action_label": label,
            "progress_status": "refused",
            "event_type": "workflow_action",
            "error": message,
        },
    )
    log_agent_event(base_dir, event)
    _append_progress_chat_message(base_dir, event)


def _log_workflow_decision(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    workflow_run_id: str,
    status: str,
    message: str,
    blockers: list[str],
    route_hint: str | None,
    next_allowed_actions: list[str],
) -> None:
    progress_status = _progress_status_from_result(status)
    if status == "waiting_for_review":
        progress_status = "needs_input"
    event = AgentWorkflowEvent(
        event_type="workflow_run",
        session_id=session_id,
        job_id=job_id,
        run_id=workflow_run_id,
        action="karen_workflow_run",
        label="Karen workflow",
        result=status,
        status=progress_status,
        message=message,
        blockers=list(blockers),
        route_hint=route_hint,
        next_allowed_actions=list(next_allowed_actions),
        details={
            "workflow_run_id": workflow_run_id,
            "action_label": "Karen workflow",
            "progress_status": progress_status,
            "event_type": "workflow_run",
            "planner_message": message,
            "next_allowed_actions": list(next_allowed_actions),
        },
    )
    log_agent_event(base_dir, event)


def _log_workflow_action_started(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    action_name: str,
    workflow_run_id: str,
    step_index: int,
    planner_message: str,
) -> None:
    label = _action_label(action_name)
    details = {
        "workflow_run_id": workflow_run_id,
        "step_index": step_index,
        "planner_message": planner_message,
        "action_label": label,
        "progress_status": "running",
        "event_type": "workflow_action",
    }
    log_agent_event(
        base_dir,
        AgentWorkflowEvent(
            event_type="workflow_action",
            session_id=session_id,
            job_id=job_id,
            run_id=workflow_run_id,
            action=action_name,
            label=label,
            result="started",
            status="running",
            message=f"{label} started.",
            details=details,
        ),
    )


def _log_workflow_intent(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    intent: WorkflowIntent,
    workflow_run_id: str,
) -> None:
    log_agent_event(
        base_dir,
        AgentWorkflowEvent(
            event_type="workflow_run",
            session_id=session_id,
            job_id=job_id,
            run_id=workflow_run_id,
            action="karen_workflow_intent",
            label="Karen workflow intent",
            result="understood",
            status="planned",
            message="Karen understood the workflow request.",
            details={
                "workflow_run_id": workflow_run_id,
                "goal": intent.goal,
                "execution_mode": intent.execution_mode,
                "allow_draft_generation": intent.allow_draft_generation,
                "allow_local_mutations": intent.allow_local_mutations,
                "allow_review_gate_crossing": intent.allow_review_gate_crossing,
                "allow_browser_launch": intent.allow_browser_launch,
                "target_job_id": intent.target_job_id,
                "progress_status": "planned",
                "event_type": "workflow_run",
            },
        ),
    )


def _append_progress_chat_message(base_dir: Path, event: AgentWorkflowEvent) -> None:
    action = WORKFLOW_ACTION_REGISTRY.get(event.action)
    if action is not None and not action.chat_milestone:
        return
    if action is not None and not action.progress_visible:
        return
    if event.status == "completed":
        content = _completed_chat_message(event)
    elif event.status in {"blocked", "needs_input", "refused", "error"}:
        content = _blocked_chat_message(event)
    else:
        return
    append_agent_chat_message(
        base_dir,
        AgentChatMessage(
            session_id=event.session_id,
            role="assistant",
            content=content,
            job_id=event.job_id,
            executed_action=event.action if event.status == "completed" else None,
        ),
    )


def _completed_chat_message(event: AgentWorkflowEvent) -> str:
    return _sentence(event.message or f"{event.label} completed.")


def _blocked_chat_message(event: AgentWorkflowEvent) -> str:
    lines = [f"I stopped at {event.label}."]
    blockers = list(event.blockers)
    if not blockers and event.message:
        blockers = [event.message]
    if blockers:
        lines.append("")
        lines.append("Blocked:")
        lines.extend(f"- {blocker}" for blocker in blockers)
    if event.route_hint:
        lines.append("")
        lines.append(f"Go to: {event.route_hint}.")
    return "\n".join(lines)


def _progress_status_from_result(result: str) -> str:
    if result in {"executed", "done"}:
        return "completed"
    if result in {"needs_input", "refused", "error"}:
        return result
    return "blocked"


def _sentence(text: str) -> str:
    value = text.strip()
    if not value:
        return "Workflow checked."
    if value.endswith((".", "!", "?")):
        return value
    return f"{value}."


def _action_label(action_name: str) -> str:
    action = WORKFLOW_ACTION_REGISTRY.get(action_name)
    if action is not None:
        return action.label
    return ACTION_LABELS.get(action_name, action_name.replace("_", " ").title())
