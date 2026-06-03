from __future__ import annotations

from pathlib import Path

from src.agent_chat import (
    get_or_create_agent_session,
    load_agent_chat_messages,
    load_agent_events,
    load_job_agent_chat_messages,
    log_agent_event,
    record_agent_chat_turn,
)
from src.schemas import AgentWorkflowEvent, AgentWorkflowState


def test_agent_chat_transcript_persists_session_and_job_copy(tmp_path: Path) -> None:
    session = get_or_create_agent_session(
        tmp_path,
        "agent-test-session",
        selected_job_id="job-001",
    )
    state = AgentWorkflowState(
        session_id=session.session_id,
        selected_job_id="job-001",
        blockers=["Review the discovered application requirements."],
        next_allowed_actions=["review_requirements"],
        pending_gate="requirements_review",
    )

    response = record_agent_chat_turn(tmp_path, state, "What is next?")

    session_messages = load_agent_chat_messages(tmp_path, session.session_id)
    job_messages = load_job_agent_chat_messages(tmp_path, "job-001")
    assert [message.role for message in session_messages] == ["user", "assistant"]
    assert [message.role for message in job_messages] == ["user", "assistant"]
    assert response.proposed_actions == ["review_requirements"]
    assert "Review the discovered application requirements" in response.content


def test_agent_event_logging_persists_session_and_job_copy(tmp_path: Path) -> None:
    event = AgentWorkflowEvent(
        session_id="agent-test-session",
        job_id="job-001",
        action="analyze_match",
        result="saved_match_analysis",
        gate="match_review",
        artifact_paths=["data/runtime/jobs/job-001/analysis.json"],
    )

    log_agent_event(tmp_path, event)

    session_events = load_agent_events(tmp_path, "agent-test-session")
    job_event_path = tmp_path / "data" / "runtime" / "jobs" / "job-001" / "events.jsonl"
    assert session_events[0].action == "analyze_match"
    assert session_events[0].gate == "match_review"
    assert job_event_path.is_file()
    assert "saved_match_analysis" in job_event_path.read_text(encoding="utf-8")
