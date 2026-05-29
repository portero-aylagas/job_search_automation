from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import src.agent_ui as agent_ui
from src.job_intake import create_job_listing
from src.schemas import AgentWorkflowState, TrackerRecord


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


class FakeColumn:
    def __init__(self, rendered: list[tuple[str, object]]) -> None:
        self.rendered = rendered

    def metric(self, label: str, value: str) -> None:
        self.rendered.append(("metric", {"label": label, "value": value}))


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
    )


def make_tracker_record(job) -> TrackerRecord:
    return TrackerRecord(
        job_id=job.id,
        title=job.title,
        company=job.company,
        source_url=str(job.source_url),
        location=job.location,
        retrieval_mode=job.retrieval_mode,
    )


def make_context(**overrides: object) -> SimpleNamespace:
    values = {
        "session_id": "karen-session-001",
        "current_page": agent_ui.AGENT_PAGE_NAME,
        "selected_job_id": "job-001",
        "pending_gate": None,
        "blockers": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_agent_page_renders_dashboard_and_chat_for_selected_job(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    job = make_job()
    context = make_context(selected_job_id=job.id)

    fake_streamlit = SimpleNamespace(
        image=lambda image, width: rendered.append(("image", {"image": image, "width": width})),
        title=lambda value: rendered.append(("title", value)),
        selectbox=lambda _label, options, index, format_func: options[index],
        info=lambda value: rendered.append(("info", value)),
        session_state={},
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    monkeypatch.setattr(
        agent_ui,
        "_current_karen_context",
        lambda _base_dir, current_page, selected_job_id: context,
    )
    monkeypatch.setattr(
        agent_ui,
        "render_karen_dashboard",
        lambda _base_dir, selected_job_id: rendered.append(
            ("dashboard", {"job_id": selected_job_id})
        ),
    )
    monkeypatch.setattr(
        agent_ui,
        "render_karen_chat_window",
        lambda _base_dir, current_page, selected_job_id: rendered.append(
            ("chat", {"page": current_page, "job_id": selected_job_id})
        ),
    )

    agent_ui.render_agent_page(Path("."), [make_tracker_record(job)])

    assert ("image", {"image": str(agent_ui.KAREN_IMAGE_PATH), "width": 128}) in rendered
    assert ("title", agent_ui.AGENT_PAGE_NAME) in rendered
    assert ("dashboard", {"job_id": job.id}) in rendered
    assert ("chat", {"page": agent_ui.AGENT_PAGE_NAME, "job_id": job.id}) in rendered


def test_karen_chat_window_processes_message_and_updates_route(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    session_state: dict[str, object] = {}
    context = make_context()

    def fake_container(**kwargs: object) -> FakeContext:
        rendered.append(("container", kwargs))
        return FakeContext()

    def fake_chat_input(label: str, key: str) -> str:
        rendered.append(("chat_input", {"label": label, "key": key}))
        return "Take me to Jobs"

    fake_streamlit = SimpleNamespace(
        container=fake_container,
        subheader=lambda value: rendered.append(("subheader", value)),
        caption=lambda value: rendered.append(("caption", value)),
        chat_input=fake_chat_input,
        rerun=lambda: rendered.append(("rerun", None)),
        session_state=session_state,
    )
    result = SimpleNamespace(
        context=make_context(session_id=context.session_id),
        intent=SimpleNamespace(target_job_id="job-002"),
        tool_result=SimpleNamespace(route_hint="Jobs"),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    monkeypatch.setattr(
        agent_ui,
        "_current_karen_context",
        lambda _base_dir, current_page, selected_job_id: context,
    )
    monkeypatch.setattr(
        agent_ui,
        "render_karen_transcript",
        lambda _base_dir, session_id, limit: rendered.append(
            ("transcript", {"session_id": session_id, "limit": limit})
        ),
    )
    monkeypatch.setattr(
        agent_ui,
        "process_karen_chat_turn",
        lambda *_args, **_kwargs: result,
    )

    agent_ui.render_karen_chat_window(
        Path("."),
        current_page=agent_ui.AGENT_PAGE_NAME,
        selected_job_id="job-001",
    )

    assert ("container", {"key": "karen_chat_panel", "border": True}) in rendered
    assert ("transcript", {"session_id": "karen-session-001", "limit": None}) in rendered
    assert ("chat_input", {"label": "Ask Karen", "key": "karen_chat_karen-session-001"}) in rendered
    assert session_state[agent_ui.KAREN_SESSION_STATE_KEY] == "karen-session-001"
    assert session_state[agent_ui.SELECTED_JOB_STATE_KEY] == "job-002"
    assert session_state[agent_ui.SELECTED_PAGE_STATE_KEY] == "Jobs"
    assert ("rerun", None) in rendered


def test_agent_status_renders_gate_blockers_and_timeline(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    fake_streamlit = SimpleNamespace(
        columns=lambda count: [FakeColumn(rendered) for _ in range(count)],
        warning=lambda value: rendered.append(("warning", value)),
        error=lambda value: rendered.append(("error", value)),
        write=lambda value: rendered.append(("write", value)),
        expander=lambda _label, expanded: FakeContext(),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    state = AgentWorkflowState(
        session_id="agent-ui",
        selected_job_id="job-001",
        pending_gate="requirements_review",
        blockers=["Review profile."],
        artifacts_present={"application_requirements": True, "application_package": False},
    )

    agent_ui.render_agent_status(state)

    assert ("metric", {"label": "Gate", "value": "requirements_review"}) in rendered
    assert ("warning", "Workflow blockers") in rendered
    assert ("write", "- Review profile.") in rendered
    assert ("write", "- Application Requirements: ready") in rendered


def test_assistant_chat_message_uses_karen_avatar(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []

    def fake_chat_message(role: str, **kwargs: object) -> FakeContext:
        rendered.append(("chat_message", {"role": role, "kwargs": kwargs}))
        return FakeContext()

    fake_streamlit = SimpleNamespace(
        chat_message=fake_chat_message,
        write=lambda value: rendered.append(("write", value)),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)

    agent_ui._render_chat_message("assistant", "Hello from Karen.")

    assert (
        "chat_message",
        {"role": "assistant", "kwargs": {"avatar": str(agent_ui.KAREN_IMAGE_PATH)}},
    ) in rendered
    assert ("write", "Hello from Karen.") in rendered


def test_gated_next_action_renders_guidance_without_open_jobs_button(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    fake_streamlit = SimpleNamespace(
        markdown=lambda value: rendered.append(("markdown", value)),
        caption=lambda value: rendered.append(("caption", value)),
        button=lambda *args, **kwargs: rendered.append(
            ("button", {"args": args, "kwargs": kwargs})
        ),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    state = AgentWorkflowState(
        session_id="agent-ui",
        selected_job_id="job-001",
        next_allowed_actions=["review_requirements"],
    )

    agent_ui.render_agent_action_buttons(Path("."), state)

    assert ("markdown", "**Next Actions**") in rendered
    assert (
        "caption",
        "Approve requirements review: open the Jobs page review panel.",
    ) in rendered
    assert not any(item[0] == "button" for item in rendered)


def test_executable_next_action_renders_without_button(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    fake_streamlit = SimpleNamespace(
        markdown=lambda value: rendered.append(("markdown", value)),
        caption=lambda value: rendered.append(("caption", value)),
        button=lambda *args, **kwargs: rendered.append(
            ("button", {"args": args, "kwargs": kwargs})
        ),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    state = AgentWorkflowState(
        session_id="agent-ui",
        selected_job_id="job-001",
        next_allowed_actions=["continue"],
    )

    agent_ui.render_agent_action_buttons(Path("."), state)

    assert ("markdown", "**Next Actions**") in rendered
    assert ("caption", "Continue workflow") in rendered
    assert not any(item[0] == "button" for item in rendered)
