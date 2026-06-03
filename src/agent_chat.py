"""Agent chat transcript persistence, response generation, and audit logging."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.paths import (
    agent_session_chat_path,
    agent_session_events_path,
    agent_session_path,
    job_agent_chat_path,
    job_agent_events_path,
)
from src.schemas import (
    AgentChatMessage,
    AgentSession,
    AgentWorkflowEvent,
    AgentWorkflowState,
)
from src.storage import append_jsonl, load_jsonl, load_model, save_model

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

ACTION_LABELS = {
    "continue": "Continue workflow",
    "continue_to_apply_assistance": "Continue to apply assistance",
    "analyze_match": "Analyze candidate/job match",
    "review_match": "Approve match analysis",
    "reject_match": "Reject match",
    "discover_requirements": "Discover application requirements",
    "review_requirements": "Approve requirements review",
    "generate_package": "Generate application package",
    "approve_package": "Approve application package",
    "reject_package": "Reject application package",
    "generate_fill_plan": "Generate fill plan",
    "review_fill_plan": "Approve fill plan",
    "prepare_apply_assistance": "Prepare apply assistance",
    "launch_browser_use": "Launch Browser Use",
}

GATE_LABELS = {
    "select_job": "Select a job before the workflow can continue.",
    "match_review": "Review the match analysis before downstream steps run.",
    "requirements_review": "Review the discovered application requirements.",
    "package_review": "Review and approve the generated application package.",
    "fill_plan_review": "Review every fill-plan field before Browser Use can receive it.",
    "browser_use_launch": "Browser Use apply assistance is ready to launch or already running.",
}


def create_agent_session_id() -> str:
    """Return a new local agent session identifier."""

    return f"agent-{uuid4().hex[:16]}"


def get_or_create_agent_session(
    base_dir: Path | str,
    session_id: str | None = None,
    *,
    selected_job_id: str | None = None,
) -> AgentSession:
    """Load or create agent session metadata."""

    current_session_id = _safe_session_id(session_id or create_agent_session_id())
    path = agent_session_path(base_dir, current_session_id)
    if path.exists():
        session = load_model(path, AgentSession)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        if selected_job_id:
            session.selected_job_id = selected_job_id
    else:
        session = AgentSession(
            session_id=current_session_id,
            selected_job_id=selected_job_id,
        )
    save_model(path, session)
    return session


def append_agent_chat_message(
    base_dir: Path | str,
    message: AgentChatMessage,
) -> None:
    """Append a chat message to the session transcript and optional job copy."""

    payload = message.model_dump(mode="json")
    append_jsonl(agent_session_chat_path(base_dir, message.session_id), payload)
    if message.job_id:
        append_jsonl(job_agent_chat_path(base_dir, message.job_id), payload)


def load_agent_chat_messages(
    base_dir: Path | str,
    session_id: str,
) -> list[AgentChatMessage]:
    """Load the persisted chat transcript for one agent session."""

    records = load_jsonl(agent_session_chat_path(base_dir, _safe_session_id(session_id)))
    return [AgentChatMessage.model_validate(record) for record in records]


def load_job_agent_chat_messages(
    base_dir: Path | str,
    job_id: str,
) -> list[AgentChatMessage]:
    """Load the persisted per-job transcript copy."""

    records = load_jsonl(job_agent_chat_path(base_dir, job_id))
    return [AgentChatMessage.model_validate(record) for record in records]


def log_agent_event(base_dir: Path | str, event: AgentWorkflowEvent) -> None:
    """Append an audit event to the session log and optional job log."""

    payload = event.model_dump(mode="json")
    append_jsonl(agent_session_events_path(base_dir, event.session_id), payload)
    if event.job_id:
        append_jsonl(job_agent_events_path(base_dir, event.job_id), payload)


def load_agent_events(base_dir: Path | str, session_id: str) -> list[AgentWorkflowEvent]:
    """Load structured workflow events for one agent session."""

    records = load_jsonl(agent_session_events_path(base_dir, _safe_session_id(session_id)))
    return [AgentWorkflowEvent.model_validate(record) for record in records]


def build_agent_response(
    state: AgentWorkflowState,
    user_message: str,
) -> AgentChatMessage:
    """Build a deterministic assistant response from current workflow state."""

    lines = []
    if state.selected_job_id:
        lines.append(f"Current job: {state.selected_job_id}.")
    else:
        lines.append("No job is selected yet.")

    if state.pending_gate:
        lines.append(GATE_LABELS[state.pending_gate])
    elif state.blockers:
        lines.append("The workflow is blocked.")
    else:
        lines.append("No human gate is currently pending.")

    if state.blockers:
        lines.append("Blockers: " + "; ".join(state.blockers))
    if state.errors:
        lines.append("Last errors: " + "; ".join(state.errors))

    if state.next_allowed_actions:
        readable_actions = [
            ACTION_LABELS.get(action, action.replace("_", " "))
            for action in state.next_allowed_actions
        ]
        lines.append("Next actions: " + "; ".join(readable_actions) + ".")
    else:
        lines.append("No workflow action is available from this state.")

    if _asks_for_safety_boundary(user_message):
        lines.append(
            "Safety boundary: Browser launch and final submission require explicit "
            "per-job session permission. I will not automate login, MFA, captcha "
            "handling, account creation, recruiter messaging, or invented candidate data."
        )

    return AgentChatMessage(
        session_id=state.session_id,
        role="assistant",
        content="\n".join(lines),
        job_id=state.selected_job_id,
        proposed_actions=list(state.next_allowed_actions),
    )


def record_agent_chat_turn(
    base_dir: Path | str,
    state: AgentWorkflowState,
    user_message: str,
) -> AgentChatMessage:
    """Persist a user chat turn and deterministic assistant response."""

    user_record = AgentChatMessage(
        session_id=state.session_id,
        role="user",
        content=user_message,
        job_id=state.selected_job_id,
    )
    append_agent_chat_message(base_dir, user_record)
    assistant_record = build_agent_response(state, user_message)
    append_agent_chat_message(base_dir, assistant_record)
    return assistant_record


def _asks_for_safety_boundary(message: str) -> bool:
    lowered = message.casefold()
    return any(
        term in lowered
        for term in ("submit", "login", "captcha", "recruiter", "browser", "apply")
    )


def _safe_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized or "/" in normalized or "\\" in normalized:
        raise ValueError("Agent session ID must be a local storage identifier.")
    if normalized in {".", ".."} or not SESSION_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Agent session ID contains unsupported characters.")
    return normalized
