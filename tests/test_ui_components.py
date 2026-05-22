from __future__ import annotations

from types import SimpleNamespace

import src.ui_components as ui_components
from src.schemas import AIWorkflowTrace
from src.ui_components import (
    format_ai_usage_summary_bullets,
    format_workflow_trace_bullets,
    render_artifact_traceability,
)


def make_trace() -> AIWorkflowTrace:
    return AIWorkflowTrace(
        workflow_name="application_requirements",
        operation="AI application requirements extraction",
        model="gpt-5.4",
        profile_name="application_requirements",
        temperature=0.0,
        max_output_tokens=6000,
        timeout_seconds=60.0,
        max_retries=2,
        retry_backoff_seconds=[1.0, 2.0],
        attempt_count=1,
        duration_ms=22200,
        recorded_at="2026-05-22T10:00:00+00:00",
    )


class FakePopover:
    def __init__(self, rendered: list[tuple[str, object]]) -> None:
        self.rendered = rendered

    def __enter__(self):
        self.rendered.append(("popover_entered", None))
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.rendered.append(("popover_exited", None))


def test_artifact_traceability_renders_in_compact_popover(monkeypatch) -> None:
    rendered: list[tuple[str, object]] = []

    def fake_popover(label: str, **kwargs: object) -> FakePopover:
        rendered.append(("popover", {"label": label, **kwargs}))
        return FakePopover(rendered)

    fake_streamlit = SimpleNamespace(
        popover=fake_popover,
        caption=lambda value: rendered.append(("caption", value)),
        write=lambda value: rendered.append(("write", value)),
    )
    monkeypatch.setattr(ui_components, "st", fake_streamlit)

    render_artifact_traceability(
        {
            "traceability": {
                "source_requirements": [
                    {
                        "label": "Cover letter required",
                        "confidence": "high",
                        "evidence": "Please upload a cover letter.",
                    }
                ],
                "source_experience_units": [
                    {
                        "title": "Automation Engineer",
                        "organization": "Example Co",
                    }
                ],
            }
        }
    )

    assert rendered[0] == (
        "popover",
        {"label": "Traceability", "type": "tertiary", "width": "content"},
    )
    assert ("write", "- Cover letter required (confidence: high)") in rendered
    assert ("write", "- Automation Engineer / Example Co") in rendered


def test_ai_usage_summary_formats_as_compact_bullets() -> None:
    bullets = format_ai_usage_summary_bullets([make_trace()])

    assert bullets == [
        "- AI calls: 1",
        "- Provider attempts: 1",
        "- Retries used: 0",
        "- Output token budget used by attempts: 6000",
        "- Worst-case output token budget with configured retries: 18000",
        "- Tool call cap: none",
    ]


def test_workflow_trace_formats_as_compact_bullets() -> None:
    bullets = format_workflow_trace_bullets(make_trace())

    assert bullets == [
        "- Workflow: application_requirements",
        "- Operation: AI application requirements extraction",
        "- Model: gpt-5.4",
        "- Profile: application_requirements",
        "- Temperature: 0.0",
        "- Max output tokens: 6000",
        "- Timeout seconds: 60.0",
        "- Retries allowed: 2",
        "- Retry backoff seconds: [1.0, 2.0]",
        "- Tool call cap: none",
        "- Attempt count: 1",
        "- Duration (ms): 22200",
        "- Recorded at: 2026-05-22T10:00:00+00:00",
    ]
