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


def test_agent_page_scopes_panel_to_selected_job(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    job = make_job()

    fake_streamlit = SimpleNamespace(
        title=lambda value: rendered.append(("title", value)),
        selectbox=lambda _label, options, format_func: options[0],
        info=lambda value: rendered.append(("info", value)),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    monkeypatch.setattr(
        agent_ui,
        "render_karen_dashboard",
        lambda _base_dir, selected_job_id: rendered.append(
            ("dashboard", {"job_id": selected_job_id})
        ),
    )

    agent_ui.render_agent_page(Path("."), [make_tracker_record(job)])

    assert ("title", "Karen") in rendered
    assert ("dashboard", {"job_id": job.id}) in rendered


def test_per_job_agent_panel_uses_same_backend_scope(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []
    job = make_job()
    fake_streamlit = SimpleNamespace(
        subheader=lambda value: rendered.append(("subheader", value)),
    )
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    monkeypatch.setattr(
        agent_ui,
        "render_agent_panel",
        lambda _base_dir, selected_job_id, compact: rendered.append(
            ("panel", {"job_id": selected_job_id, "compact": compact})
        ),
    )

    agent_ui.render_per_job_agent_panel(Path("."), job)

    assert rendered == [
        ("subheader", "Karen"),
        ("panel", {"job_id": job.id, "compact": True}),
    ]


def test_karen_chat_window_uses_persistent_panel_container_keys(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []

    def fake_container(**kwargs: object) -> FakeContext:
        rendered.append(("container", kwargs))
        return FakeContext()

    def fake_chat_input(label: str, key: str) -> None:
        rendered.append(("chat_input", {"label": label, "key": key}))
        return None

    fake_streamlit = SimpleNamespace(
        container=fake_container,
        subheader=lambda value: rendered.append(("subheader", value)),
        markdown=lambda value, unsafe_allow_html=False: rendered.append(
            (
                "markdown",
                {"value": value, "unsafe_allow_html": unsafe_allow_html},
            )
        ),
        chat_input=fake_chat_input,
    )
    context = SimpleNamespace(session_id="karen-session-001")
    monkeypatch.setattr(agent_ui, "st", fake_streamlit)
    monkeypatch.setattr(
        agent_ui,
        "_current_karen_context",
        lambda _base_dir, current_page, selected_job_id: context,
    )
    monkeypatch.setattr(
        agent_ui,
        "_render_karen_context_summary",
        lambda _context: rendered.append(("context", context.session_id)),
    )
    monkeypatch.setattr(
        agent_ui,
        "render_karen_transcript",
        lambda _base_dir, session_id, limit: rendered.append(
            ("transcript", {"session_id": session_id, "limit": limit})
        ),
    )

    agent_ui.render_karen_chat_window(
        Path("."),
        current_page="Jobs",
        selected_job_id="job-001",
    )

    containers = [item[1] for item in rendered if item[0] == "container"]
    assert {"key": "karen_panel", "border": True} in containers
    assert {"key": "karen_context_panel", "border": False} in containers
    assert {"key": "karen_chat_body", "border": False} in containers
    assert {"key": "karen_chat_input_bar", "border": False} in containers
    assert all(
        "height" not in kwargs
        for kwargs in containers
        if kwargs.get("key") == "karen_chat_body"
    )
    assert ("transcript", {"session_id": "karen-session-001", "limit": None}) in rendered
    assert ("chat_input", {"label": "Ask Karen", "key": "karen_chat_karen-session-001"}) in rendered
    assert any(
        item[0] == "markdown" and "karen-chat-body-anchor" in item[1]["value"]
        for item in rendered
    )
    assert any(
        item[0] == "markdown" and "karen-chat-input-anchor" in item[1]["value"]
        for item in rendered
    )


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
