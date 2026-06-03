"""Deterministic planner for the known-job application workflow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

WorkflowGoal = Literal[
    "generate_application_data",
    "mark_current_gate_reviewed",
    "generate_and_review_application_data",
    "continue_to_next_gate",
    "continue_until_blocked",
    "prepare_browser_application",
    "launch_browser_application",
    "prepare_manual_application",
    "apply_without_browser_use",
    "stop_browser_session",
]
ExecutionMode = Literal["manual", "browser_use"]
PlannerStatus = Literal["action", "blocked", "done", "waiting_for_review", "refused"]


class WorkflowIntent(BaseModel):
    """Structured workflow intent parsed from a Karen chat message."""

    goal: WorkflowGoal
    target_job_id: str | None = None
    allow_draft_generation: bool = False
    allow_local_mutations: bool = False
    allow_review_gate_crossing: bool = False
    allow_browser_launch: bool = False
    execution_mode: ExecutionMode = "manual"
    confidence: Literal["low", "medium", "high"] = "medium"
    reasoning_summary: str = ""
    requires_clarification: bool = False
    clarification_question: str = ""

    @field_validator("target_job_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("reasoning_summary", "clarification_question", mode="before")
    @classmethod
    def _blank_to_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class PlannerDecision(BaseModel):
    """Planner output for one workflow loop iteration."""

    status: PlannerStatus
    action_name: str | None = None
    message: str
    route_hint: str | None = None
    blockers: list[str] = Field(default_factory=list)


REVIEW_ACTION_BY_GATE = {
    "requirements_review": "review_requirements",
    "package_review": "review_application_package",
    "fill_plan_review": "review_fill_plan",
}


def planner_next_action(state, intent: WorkflowIntent) -> PlannerDecision:
    """Return the next allowed action or a deterministic stop reason."""

    if intent.requires_clarification:
        return PlannerDecision(
            status="refused",
            message=intent.clarification_question or "Karen needs clarification first.",
            route_hint=state.route_hint,
        )

    if intent.goal == "stop_browser_session":
        return PlannerDecision(
            status="action",
            action_name="stop_browser_use_session",
            message="Stopping the active Browser Use session.",
        )

    if not state.selected_job_id:
        return PlannerDecision(
            status="blocked",
            message="Select a job before running a job-scoped workflow action.",
            route_hint="Jobs",
            blockers=["Select a job before running the workflow."],
        )

    if state.current_blockers:
        return PlannerDecision(
            status="blocked",
            message="Karen is blocked by the current workflow state.",
            route_hint=state.route_hint,
            blockers=list(state.current_blockers),
        )

    if state.pending_gate in REVIEW_ACTION_BY_GATE:
        action_name = REVIEW_ACTION_BY_GATE[state.pending_gate]
        if _intent_allows_current_review_gate(intent):
            return PlannerDecision(
                status="action",
                action_name=action_name,
                message=f"Reviewing the current gate: {state.pending_gate}.",
                route_hint="Jobs",
            )
        return PlannerDecision(
            status="waiting_for_review",
            message=f"Waiting for human review at {state.pending_gate}.",
            route_hint="Jobs",
        )

    if intent.goal == "mark_current_gate_reviewed":
        return PlannerDecision(
            status="done",
            message="No reviewable artifact is currently waiting.",
            route_hint=state.route_hint,
        )

    if not state.requirements_exists:
        return _draft_action_or_refusal(
            intent,
            "discover_requirements",
            "Discovering application requirements.",
        )

    if not state.package_exists:
        if _intent_is_manual_only(intent) and intent.goal == "apply_without_browser_use":
            return _draft_action_or_refusal(
                intent,
                "generate_application_package",
                "Generating application package for manual application.",
            )
        return _draft_action_or_refusal(
            intent,
            "generate_application_package",
            "Generating application package.",
        )

    if intent.goal in {
        "generate_application_data",
        "generate_and_review_application_data",
    }:
        return PlannerDecision(
            status="done",
            message="Application package data is generated.",
            route_hint="Jobs",
        )

    if not state.fill_plan_exists:
        return _draft_action_or_refusal(
            intent,
            "generate_fill_plan",
            "Generating application fill plan.",
        )

    if _intent_is_manual_only(intent):
        return PlannerDecision(
            status="done",
            message="The job is prepared for manual application.",
            route_hint="Jobs",
        )

    if intent.execution_mode == "browser_use" and intent.goal in {
        "prepare_browser_application",
        "launch_browser_application",
    }:
        if intent.goal == "prepare_browser_application" and not intent.allow_browser_launch:
            return PlannerDecision(
                status="action",
                action_name="prepare_apply_assistance",
                message="Checking Browser Use apply assistance readiness.",
                route_hint="Jobs",
            )
        return PlannerDecision(
            status="action",
            action_name="launch_browser_use",
            message="Launching Browser Use apply assistance.",
            route_hint="Jobs",
        )

    return PlannerDecision(
        status="done",
        message="No further workflow action is available for this request.",
        route_hint="Jobs",
    )


def _draft_action_or_refusal(
    intent: WorkflowIntent,
    action_name: str,
    message: str,
) -> PlannerDecision:
    if intent.allow_draft_generation or intent.allow_local_mutations:
        return PlannerDecision(status="action", action_name=action_name, message=message)
    return PlannerDecision(
        status="refused",
        message="This workflow step needs explicit draft-generation permission.",
    )


def _intent_allows_current_review_gate(intent: WorkflowIntent) -> bool:
    if not intent.allow_review_gate_crossing:
        return False
    return intent.goal in {
        "mark_current_gate_reviewed",
        "generate_and_review_application_data",
        "continue_until_blocked",
        "prepare_browser_application",
        "launch_browser_application",
        "prepare_manual_application",
        "apply_without_browser_use",
    }


def _intent_is_manual_only(intent: WorkflowIntent) -> bool:
    return intent.execution_mode == "manual" or intent.goal in {
        "prepare_manual_application",
        "apply_without_browser_use",
    }
