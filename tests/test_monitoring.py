from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.monitoring import LangSmithMonitoringError, langsmith_monitoring_summary


def test_langsmith_monitoring_returns_unconfigured_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")

    payload = langsmith_monitoring_summary(days=7)

    assert payload["configured"] is False
    assert payload["project_name"] == "job-search-automation"
    assert payload["totals"]["run_count"] == 0
    assert payload["recent_runs"] == []


def test_langsmith_monitoring_normalizes_stats_and_recent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")
    monkeypatch.setenv("LANGSMITH_DASHBOARD_URL", "https://smith.langchain.com/dashboards/1")
    client = FakeLangSmithClient()

    payload = langsmith_monitoring_summary(days=7, client_factory=lambda: client)

    assert payload["configured"] is True
    assert payload["dashboard_url"] == "https://smith.langchain.com/dashboards/1"
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
    assert payload["recent_runs"] == [
        {
            "id": "run-1",
            "name": "cv_extraction",
            "run_type": "chain",
            "start_time": "2026-06-03T10:00:00+00:00",
            "end_time": "2026-06-03T10:00:02+00:00",
            "status": "complete",
            "error": None,
            "total_tokens": 400,
            "total_cost": 0.12,
            "url": "https://smith.langchain.com/r/run-1",
        }
    ]
    assert client.stats_errors == [None, True]
    assert client.list_project_name == "job-search-automation"


def test_langsmith_monitoring_wraps_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")

    with pytest.raises(LangSmithMonitoringError, match="Could not load LangSmith monitoring"):
        langsmith_monitoring_summary(client_factory=lambda: BrokenLangSmithClient())


class FakeLangSmithClient:
    def __init__(self) -> None:
        self.stats_errors: list[bool | None] = []
        self.list_project_name = ""

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
        return [
            SimpleNamespace(
                id="run-1",
                name="cv_extraction",
                run_type="chain",
                start_time=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 3, 10, 0, 2, tzinfo=UTC),
                error=None,
                total_tokens=400,
                total_cost=0.12,
            )
        ]

    def get_run_url(self, *, run: SimpleNamespace, project_name: str) -> str:
        return f"https://smith.langchain.com/r/{run.id}"


class BrokenLangSmithClient:
    def get_run_stats(self, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("network unavailable")
