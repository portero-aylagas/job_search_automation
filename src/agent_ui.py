"""Reusable Streamlit UI for Karen's chat and workflow status panels."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.agent_chat import ACTION_LABELS, load_agent_chat_messages
from src.agent_workflow import run_agent_workflow
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.tools import build_karen_context
from src.schemas import AgentWorkflowState, JobListing, TrackerRecord

KAREN_SESSION_STATE_KEY = "karen_session_id"
SELECTED_JOB_STATE_KEY = "selected_job_id"
SELECTED_PAGE_STATE_KEY = "selected_page"
CHAT_BLOCKED_ACTIONS = {
    "review_requirements",
    "approve_package",
    "reject_package",
    "review_fill_plan",
    "launch_browser_use",
}


def render_agent_page(base_dir: Path, tracker_records: list[TrackerRecord]) -> None:
    """Render Karen's expanded dashboard page."""

    st.title("Karen")
    selected_job_id = _render_job_selector(tracker_records)
    if selected_job_id is None:
        st.info("No jobs have been added yet.")
        render_karen_dashboard(base_dir, selected_job_id=None)
        return
    render_karen_dashboard(base_dir, selected_job_id=selected_job_id)


def render_per_job_agent_panel(base_dir: Path, job: JobListing) -> None:
    """Render a compact compatibility panel for a selected job."""

    st.subheader("Karen")
    render_agent_panel(base_dir, selected_job_id=job.id, compact=True)


def render_karen_chat_window(
    base_dir: Path,
    *,
    current_page: str,
    selected_job_id: str | None,
) -> None:
    """Render Karen as the persistent right-side chat window."""

    st.subheader("Karen")
    context = _current_karen_context(
        base_dir,
        current_page=current_page,
        selected_job_id=selected_job_id,
    )
    _render_karen_context_summary(context)
    render_karen_transcript(base_dir, context.session_id, limit=8)

    if not hasattr(st, "chat_input"):
        return

    st.markdown('<span class="karen-chat-input-anchor"></span>', unsafe_allow_html=True)
    user_message = st.chat_input("Ask Karen", key=f"karen_chat_{context.session_id}")
    if not user_message:
        return

    result = process_karen_chat_turn(
        base_dir,
        current_page=current_page,
        selected_job_id=selected_job_id,
        user_message=user_message,
        session_id=context.session_id,
    )
    _set_session_value(KAREN_SESSION_STATE_KEY, result.context.session_id)
    if result.intent and result.intent.target_job_id:
        _set_session_value(SELECTED_JOB_STATE_KEY, result.intent.target_job_id)
    if result.tool_result and result.tool_result.route_hint:
        _set_session_value(SELECTED_PAGE_STATE_KEY, result.tool_result.route_hint)
    st.rerun()


def render_karen_dashboard(base_dir: Path, *, selected_job_id: str | None) -> None:
    """Render Karen's expanded status dashboard without a second chat input."""

    context = _current_karen_context(
        base_dir,
        current_page="Agent",
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
        current_page="Jobs" if compact else "Agent",
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
    """Render safe explicit workflow buttons and route gated reviews to Jobs."""

    if not state.next_allowed_actions:
        return

    st.markdown("**Next Actions**")
    for action in state.next_allowed_actions:
        label = ACTION_LABELS.get(action, action.replace("_", " ").title())
        if action in CHAT_BLOCKED_ACTIONS:
            st.caption(f"{label}: open the Jobs page review panel.")
            if st.button(
                "Open Jobs",
                key=f"karen_route_jobs_{state.session_id}_{action}",
            ):
                _set_session_value(SELECTED_PAGE_STATE_KEY, "Jobs")
                st.rerun()
            continue

        button_type = "primary" if action == "continue" else "secondary"
        if st.button(label, key=f"karen_action_{state.session_id}_{action}", type=button_type):
            run_agent_workflow(
                base_dir,
                session_id=state.session_id,
                selected_job_id=state.selected_job_id,
                action=action,
            )
            st.rerun()


def render_agent_chat(base_dir: Path, state: AgentWorkflowState) -> None:
    """Render Karen transcript compatibility view for tests and old callers."""

    st.markdown("**Chat**")
    render_karen_transcript(base_dir, state.session_id, limit=20)


def render_karen_transcript(base_dir: Path, session_id: str, *, limit: int) -> None:
    """Render persisted Karen transcript messages."""

    for message in load_agent_chat_messages(base_dir, session_id)[-limit:]:
        _render_chat_message(message.role, message.content)


def _render_job_selector(tracker_records: list[TrackerRecord]) -> str | None:
    if not tracker_records:
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
):
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


def _render_karen_context_summary(context) -> None:
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
        with st.chat_message(role):
            st.write(content)
        return
    st.markdown(f"**{role.title()}**")
    st.write(content)


def _render_list(label: str, items: list[str]) -> None:
    st.markdown(f"**{label}**")
    if not items:
        st.caption("None")
        return
    for item in items:
        st.write(f"- {item}")


def _get_session_value(key: str, default: object | None = None) -> object | None:
    session_state = getattr(st, "session_state", None)
    if session_state is None:
        return default
    return session_state.get(key, default)


def _set_session_value(key: str, value: object) -> None:
    session_state = getattr(st, "session_state", None)
    if session_state is not None:
        session_state[key] = value
