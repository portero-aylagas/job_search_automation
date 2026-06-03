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

from src.agent_chat import log_agent_event
from src.agents.karen.policy import PermissionLevel
from src.schemas import AgentWorkflowEvent
from src.workflow.action_registry import (
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

    for _ in range(MAX_WORKFLOW_STEPS):
        state = load_current_workflow_state(base_path, active_job_id)
        decision = planner_next_action(state, intent)

        if decision.status == "action" and decision.action_name:
            policy_message = _policy_refusal(decision.action_name, intent)
            if policy_message:
                return _result_from_state(
                    state,
                    status="refused",
                    message=policy_message,
                    executed_actions=executed_actions,
                )

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
            )
            if action_result.status not in {"executed", "done"}:
                refreshed = load_current_workflow_state(base_path, active_job_id)
                return _result_from_state(
                    refreshed,
                    status=action_result.status,
                    message=action_result.message,
                    blockers=action_result.blockers,
                    route_hint=action_result.route_hint,
                    executed_actions=executed_actions,
                    artifact_paths=artifact_paths,
                    event_details=action_result.event_details,
                )
            if action_result.action_name in {
                "launch_browser_use",
                "prepare_apply_assistance",
                "prepare_manual_application",
                "stop_browser_use_session",
                "kill_browser_use_processes",
            }:
                refreshed = load_current_workflow_state(base_path, active_job_id)
                return _result_from_state(
                    refreshed,
                    status="done" if action_result.status == "executed" else action_result.status,
                    message=action_result.message,
                    route_hint=action_result.route_hint,
                    executed_actions=executed_actions,
                    artifact_paths=artifact_paths,
                    event_details=action_result.event_details,
                )
            continue

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
    return _result_from_state(
        state,
        status="blocked",
        message="Maximum Karen workflow steps reached.",
        blockers=["Maximum Karen workflow steps reached."],
        executed_actions=executed_actions,
        artifact_paths=artifact_paths,
    )


def _policy_refusal(action_name: str, intent: WorkflowIntent) -> str:
    action = get_workflow_action(action_name)
    if action is None:
        return f"Workflow action is not registered: {action_name}."
    if action.review_gate and not intent.allow_review_gate_crossing:
        return "Karen needs explicit review-gate permission before marking this artifact reviewed."
    if action.external_effect:
        if action.permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION:
            if action.name in {"stop_browser_use_session", "kill_browser_use_processes"}:
                if intent.allow_browser_launch or intent.allow_local_mutations:
                    return ""
            if not intent.allow_browser_launch or intent.execution_mode != "browser_use":
                return "Karen needs explicit Browser Use launch permission for this action."
    if action.permission_level == PermissionLevel.DRAFT_ONLY and not (
        intent.allow_draft_generation or intent.allow_local_mutations
    ):
        return "Karen needs explicit draft-generation permission for this action."
    if (
        action.permission_level == PermissionLevel.MUTATES_LOCAL_STATE
        and not action.review_gate
        and not intent.allow_local_mutations
    ):
        return "Karen needs explicit local workflow mutation permission for this action."
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


def _log_workflow_action(
    base_dir: Path,
    *,
    session_id: str,
    job_id: str | None,
    result: WorkflowActionResult,
) -> None:
    log_agent_event(
        base_dir,
        AgentWorkflowEvent(
            session_id=session_id,
            job_id=job_id,
            action=result.action_name,
            result=result.status,
            gate=None,
            artifact_paths=result.artifact_paths,
            details=result.event_details,
        ),
    )
