from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.monitoring import (
    LangSmithMonitoringError,
    _discover_custom_dashboard_url,
    langsmith_monitoring_summary,
)


def test_langsmith_monitoring_returns_unconfigured_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")

    payload = langsmith_monitoring_summary(days=7)

    assert payload["configured"] is False
    assert payload["project_name"] == "job-search-automation"
    assert payload["totals"]["run_count"] == 0
    assert payload["trace_view_label"] == "CV & Certificates Extraction"
    assert payload["cv_extraction_dashboard_label"] == "job-search-automation_cv-extraction"
    assert payload["cv_extraction_dashboard_url"] == ""
    assert payload["cv_certificate_traces"] == []


def test_langsmith_monitoring_normalizes_stats_and_extraction_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")
    monkeypatch.setenv("LANGSMITH_DASHBOARD_URL", "https://smith.langchain.com/dashboards/1")
    monkeypatch.setenv(
        "LANGSMITH_CV_CERTIFICATES_TRACE_VIEW_URL",
        "https://smith.langchain.com/o/example/projects/p/traces?view=cv",
    )
    monkeypatch.setenv(
        "LANGSMITH_CV_EXTRACTION_DASHBOARD_URL",
        "https://smith.langchain.com/o/example/dashboards/cv",
    )
    client = FakeLangSmithClient()

    payload = langsmith_monitoring_summary(days=7, client_factory=lambda: client)

    assert payload["configured"] is True
    assert payload["dashboard_url"] == "https://smith.langchain.com/dashboards/1"
    assert payload["trace_view_label"] == "CV & Certificates Extraction"
    assert (
        payload["trace_view_url"]
        == "https://smith.langchain.com/o/example/projects/p/traces?view=cv"
    )
    assert payload["cv_extraction_dashboard_label"] == "job-search-automation_cv-extraction"
    assert (
        payload["cv_extraction_dashboard_url"]
        == "https://smith.langchain.com/o/example/dashboards/cv"
    )
    assert payload["window_days"] == 7
    assert payload["totals"] == {
        "run_count": 12,
        "failed_run_count": 2,
        "error_rate": 0.25,
        "total_cost": 1.25,
        "total_tokens": 3400,
        "latency_p50": 1.2,
        "latency_p99": 4.8,
    }
    assert payload["cv_certificate_traces"] == [
        {
            "id": "run-1",
            "name": "LangGraph",
            "run_type": "chain",
            "start_time": "2026-06-03T10:00:00+00:00",
            "end_time": "2026-06-03T10:00:02+00:00",
            "status": "complete",
            "error": None,
            "total_tokens": 400,
            "total_cost": 0.12,
            "url": "https://smith.langchain.com/r/run-1",
        },
        {
            "id": "run-2",
            "name": "LangGraph",
            "run_type": "chain",
            "start_time": "2026-06-03T10:05:00+00:00",
            "end_time": "2026-06-03T10:05:02+00:00",
            "status": "complete",
            "error": None,
            "total_tokens": 250,
            "total_cost": 0.08,
            "url": "https://smith.langchain.com/r/run-2",
        }
    ]
    assert client.stats_errors == [None, True]
    assert client.list_project_name == "job-search-automation"
    assert client.list_tree_filter == (
        'or(eq(name, "extract_cv_data"), eq(name, "inspect_cv_document_agent"))'
    )


def test_langsmith_monitoring_wraps_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")

    with pytest.raises(LangSmithMonitoringError, match="Could not load LangSmith monitoring"):
        langsmith_monitoring_summary(client_factory=lambda: BrokenLangSmithClient())


def test_langsmith_monitoring_discovers_custom_dashboard_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        if url.endswith("/charts/section"):
            return FakeResponse(
                [
                    {
                        "title": "job-search-automation_cv-extraction",
                        "id": "58980282-ca5c-4205-b397-07991676e646",
                    }
                ]
            )
        if url.endswith("/workspaces"):
            return FakeResponse(
                [
                    {
                        "id": "c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57",
                        "is_deleted": False,
                    }
                ]
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("src.monitoring.requests.get", fake_get)

    assert _discover_custom_dashboard_url("job-search-automation_cv-extraction") == (
        "https://eu.smith.langchain.com/o/"
        "c8a8962b-4b69-4a4c-a6b6-d7d458b6ab57/dashboards/"
        "58980282-ca5c-4205-b397-07991676e646"
    )


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeLangSmithClient:
    def __init__(self) -> None:
        self.stats_errors: list[bool | None] = []
        self.list_project_name = ""
        self.list_tree_filter = ""

    def get_run_stats(self, **kwargs: object) -> dict[str, object]:
        error = kwargs.get("error")
        self.stats_errors.append(error if isinstance(error, bool) else None)
        if kwargs.get("error") is True:
            return {"run_count": 2}
        return {
            "run_count": 12,
            "error_rate": 0.25,
            "total_cost": 1.25,
            "total_tokens": 3400,
            "latency_p50": 1.2,
            "latency_p99": 4.8,
        }

    def list_runs(self, **kwargs: object) -> list[SimpleNamespace]:
        self.list_project_name = str(kwargs.get("project_name"))
        self.list_tree_filter = str(kwargs.get("tree_filter"))
        return [
            SimpleNamespace(
                id="run-1",
                name="LangGraph",
                run_type="chain",
                start_time=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 3, 10, 0, 2, tzinfo=UTC),
                error=None,
                total_tokens=400,
                total_cost=0.12,
            ),
            SimpleNamespace(
                id="run-2",
                name="LangGraph",
                run_type="chain",
                start_time=datetime(2026, 6, 3, 10, 5, tzinfo=UTC),
                end_time=datetime(2026, 6, 3, 10, 5, 2, tzinfo=UTC),
                error=None,
                total_tokens=250,
                total_cost=0.08,
            )
        ]

    def get_run_url(self, *, run: SimpleNamespace, project_name: str) -> str:
        return f"https://smith.langchain.com/r/{run.id}"


class BrokenLangSmithClient:
    def get_run_stats(self, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("network unavailable")
