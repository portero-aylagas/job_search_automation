"""Streamlit UI for Karen's Agent tab chat and workflow controls."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

import streamlit as st

from src.agent_chat import ACTION_LABELS, load_agent_chat_messages
from src.agent_workflow import run_agent_workflow
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.tools import build_karen_context
from src.job_workspace_ui import SELECTED_JOB_STATE_KEY
from src.schemas import AgentWorkflowState, JobListing, TrackerRecord

AGENT_PAGE_NAME = "Agent Karen"
KAREN_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "karen.png"
KAREN_SESSION_STATE_KEY = "karen_session_id"
SELECTED_PAGE_STATE_KEY = "selected_page"
CHAT_BLOCKED_ACTIONS = {
    "review_requirements",
    "approve_package",
    "reject_package",
    "review_fill_plan",
    "launch_browser_use",
}


def render_agent_page(base_dir: Path, tracker_records: list[TrackerRecord]) -> None:
    """Render Karen's top-level Agent tab with chat behavior."""

    _render_karen_header()
    selected_job_id = _render_job_selector(tracker_records)
    context = _current_karen_context(
        base_dir,
        current_page=AGENT_PAGE_NAME,
        selected_job_id=selected_job_id,
    )

    render_karen_dashboard(base_dir, selected_job_id=context.selected_job_id)
    render_karen_chat_window(
        base_dir,
        current_page=AGENT_PAGE_NAME,
        selected_job_id=context.selected_job_id,
    )


def render_per_job_agent_panel(base_dir: Path, job: JobListing) -> None:
    """Render a compact workflow panel for a selected job."""

    st.subheader("Karen")
    render_agent_panel(base_dir, selected_job_id=job.id, compact=True)


def render_karen_chat_window(
    base_dir: Path,
    *,
    current_page: str,
    selected_job_id: str | None,
) -> None:
    """Render Karen's transcript and process a chat input turn."""

    context = _current_karen_context(
        base_dir,
        current_page=current_page,
        selected_job_id=selected_job_id,
    )
    with _optional_container(key="karen_chat_panel", border=True):
        st.subheader("Chat")
        _render_karen_context_summary(context)
        render_karen_transcript(base_dir, context.session_id, limit=None)

        chat_input = getattr(st, "chat_input", None)
        if chat_input is None:
            return
        user_message = chat_input("Ask Karen", key=f"karen_chat_{context.session_id}")

    if not user_message:
        return

    result = process_karen_chat_turn(
        base_dir,
        current_page=current_page,
        selected_job_id=context.selected_job_id,
        user_message=user_message,
        session_id=context.session_id,
    )
    _set_session_value(KAREN_SESSION_STATE_KEY, result.context.session_id)
    if result.intent and result.intent.target_job_id:
        _set_session_value(SELECTED_JOB_STATE_KEY, result.intent.target_job_id)
    if result.tool_result and result.tool_result.route_hint:
        _set_session_value(SELECTED_PAGE_STATE_KEY, _normalize_route(result.tool_result.route_hint))
    _rerun()


def render_karen_dashboard(base_dir: Path, *, selected_job_id: str | None) -> None:
    """Render Karen's workflow status dashboard for the active chat session."""

    context = _current_karen_context(
        base_dir,
        current_page=AGENT_PAGE_NAME,
        selected_job_id=selected_job_id,
    )
    state = run_agent_workflow(
        base_dir,
        session_id=context.session_id,
        selected_job_id=context.selected_job_id,
    )

    render_agent_status(state)
    render_agent_action_buttons(base_dir, state)


def render_agent_panel(
    base_dir: Path,
    *,
    selected_job_id: str | None,
    compact: bool = False,
) -> AgentWorkflowState:
    """Render workflow status and safe explicit action buttons."""

    context = _current_karen_context(
        base_dir,
        current_page="Jobs" if compact else AGENT_PAGE_NAME,
        selected_job_id=selected_job_id,
    )
    state = run_agent_workflow(
        base_dir,
        session_id=context.session_id,
        selected_job_id=context.selected_job_id,
    )

    render_agent_status(state, compact=compact)
    render_agent_action_buttons(base_dir, state)
    return state


def render_agent_status(state: AgentWorkflowState, *, compact: bool = False) -> None:
    """Render workflow status and currently visible gates."""

    columns = st.columns(3)
    columns[0].metric("Job", state.selected_job_id or "None")
    columns[1].metric("Gate", state.pending_gate or "None")
    columns[2].metric("Actions", str(len(state.next_allowed_actions)))

    if state.blockers:
        st.warning("Workflow blockers")
        for blocker in state.blockers:
            st.write(f"- {blocker}")
    if state.errors:
        st.error("Last workflow error")
        for error in state.errors:
            st.write(f"- {error}")

    if compact:
        return

    with st.expander("Workflow timeline", expanded=False):
        for label, present in state.artifacts_present.items():
            marker = "ready" if present else "missing"
            st.write(f"- {label.replace('_', ' ').title()}: {marker}")


def render_agent_action_buttons(base_dir: Path, state: AgentWorkflowState) -> None:
    """Render next workflow actions as static guidance."""

    if not state.next_allowed_actions:
        return

    _ = base_dir
    st.markdown("**Next Actions**")
    for action in state.next_allowed_actions:
        label = ACTION_LABELS.get(action, action.replace("_", " ").title())
        if action in CHAT_BLOCKED_ACTIONS:
            st.caption(f"{label}: open the Jobs page review panel.")
            continue
        st.caption(label)


def render_agent_chat(base_dir: Path, state: AgentWorkflowState) -> None:
    """Render Karen transcript compatibility view for tests and old callers."""

    st.markdown("**Chat**")
    render_karen_transcript(base_dir, state.session_id, limit=20)


def render_karen_transcript(base_dir: Path, session_id: str, *, limit: int | None) -> None:
    """Render persisted Karen transcript messages."""

    messages = load_agent_chat_messages(base_dir, session_id)
    if limit is not None:
        messages = messages[-limit:]

    for message in messages:
        _render_chat_message(message.role, message.content)


def _render_job_selector(tracker_records: list[TrackerRecord]) -> str | None:
    if not tracker_records:
        st.info("No jobs have been added yet.")
        return None

    sorted_records = sorted(
        tracker_records,
        key=lambda record: (record.company.lower(), record.title.lower(), record.job_id),
    )
    selected_job_id = _get_session_value(SELECTED_JOB_STATE_KEY)
    selected_index = next(
        (
            index
            for index, record in enumerate(sorted_records)
            if record.job_id == selected_job_id
        ),
        0,
    )
    try:
        selected = st.selectbox(
            "Job",
            sorted_records,
            index=selected_index,
            format_func=lambda record: f"{record.company} / {record.title}",
        )
    except TypeError:
        selected = st.selectbox(
            "Job",
            sorted_records,
            format_func=lambda record: f"{record.company} / {record.title}",
        )
    _set_session_value(SELECTED_JOB_STATE_KEY, selected.job_id)
    return selected.job_id


def _current_karen_context(
    base_dir: Path,
    *,
    current_page: str,
    selected_job_id: str | None,
) -> Any:
    session_id = _get_session_value(KAREN_SESSION_STATE_KEY)
    context = build_karen_context(
        base_dir,
        current_page=current_page,
        selected_job_id=selected_job_id,
        session_id=session_id,
    )
    _set_session_value(KAREN_SESSION_STATE_KEY, context.session_id)
    if context.selected_job_id:
        _set_session_value(SELECTED_JOB_STATE_KEY, context.selected_job_id)
    return context


def _render_karen_context_summary(context: Any) -> None:
    st.caption(f"Page: {context.current_page}")
    if context.selected_job_id:
        st.caption(f"Job: {context.selected_job_id}")
    if context.pending_gate:
        st.info(f"Pending gate: {context.pending_gate}")
    if context.blockers:
        with st.expander("Blockers", expanded=False):
            for blocker in context.blockers:
                st.write(f"- {blocker}")


def _render_chat_message(role: str, content: str) -> None:
    if hasattr(st, "chat_message"):
        avatar = (
            str(KAREN_IMAGE_PATH)
            if role == "assistant" and KAREN_IMAGE_PATH.exists()
            else None
        )
        chat_message_kwargs = {"avatar": avatar} if avatar else {}
        with st.chat_message(role, **chat_message_kwargs):
            st.write(content)
        return
    st.markdown(f"**{role.title()}**")
    st.write(content)


def _render_karen_header() -> None:
    if KAREN_IMAGE_PATH.exists() and hasattr(st, "image"):
        st.image(str(KAREN_IMAGE_PATH), width=128)
    st.title(AGENT_PAGE_NAME)


def _normalize_route(route_hint: str) -> str:
    if route_hint == "Agent":
        return AGENT_PAGE_NAME
    return route_hint


def _optional_container(**kwargs: object):
    container = getattr(st, "container", None)
    if container is None:
        return nullcontext()
    return container(**kwargs)


def _rerun() -> None:
    rerun = getattr(st, "rerun", None)
    if rerun is not None:
        rerun()


def _get_session_value(key: str, default: object | None = None) -> object | None:
    session_state = getattr(st, "session_state", None)
    if session_state is None:
        return default
    return session_state.get(key, default)


def _set_session_value(key: str, value: object) -> None:
    session_state = getattr(st, "session_state", None)
    if session_state is not None:
        session_state[key] = value
