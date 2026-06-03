"""LangSmith monitoring summaries for the React Monitoring tab."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import requests

CV_EXTRACTION_DASHBOARD_TITLE = "job-search-automation_cv-extraction"
CV_CERTIFICATE_TRACE_NODE_NAMES = {
    "extract_cv_data",
    "inspect_cv_document_agent",
}
CV_CERTIFICATE_TRACE_VIEW_LABEL = "CV & Certificates Extraction"


class LangSmithMonitoringError(RuntimeError):
    """Raised when LangSmith monitoring data cannot be loaded."""


def langsmith_monitoring_summary(
    *,
    days: int = 7,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return a browser-safe LangSmith monitoring summary.

    Args:
        days: Number of days to include in the summary window.
        client_factory: Optional test seam for a LangSmith client.

    Returns:
        A JSON-serializable monitoring payload.

    Raises:
        LangSmithMonitoringError: If LangSmith is configured but the API request fails.
    """

    project_name = os.getenv("LANGSMITH_PROJECT", "").strip()
    dashboard_url = os.getenv("LANGSMITH_DASHBOARD_URL", "").strip()
    trace_view_url = (
        os.getenv("LANGSMITH_CV_CERTIFICATES_TRACE_VIEW_URL", "").strip()
        or dashboard_url
    )
    cv_extraction_dashboard_url = _cv_extraction_dashboard_url(
        client_factory=client_factory,
    )
    window_days = _window_days(days)

    if not os.getenv("LANGSMITH_API_KEY") or not project_name:
        return {
            "configured": False,
            "project_name": project_name,
            "dashboard_url": dashboard_url,
            "trace_view_label": CV_CERTIFICATE_TRACE_VIEW_LABEL,
            "trace_view_url": trace_view_url,
            "cv_extraction_dashboard_label": CV_EXTRACTION_DASHBOARD_TITLE,
            "cv_extraction_dashboard_url": cv_extraction_dashboard_url,
            "window_days": window_days,
            "totals": _empty_totals(),
            "cv_certificate_traces": [],
            "message": (
                "Set LANGSMITH_API_KEY and LANGSMITH_PROJECT to load LangSmith monitoring."
            ),
        }

    start_time = datetime.now(UTC) - timedelta(days=window_days)
    try:
        client = client_factory() if client_factory is not None else _default_langsmith_client()
        stats = client.get_run_stats(
            project_names=[project_name],
            start_time=start_time.isoformat(),
            is_root=True,
        )
        failed_stats = client.get_run_stats(
            project_names=[project_name],
            start_time=start_time.isoformat(),
            is_root=True,
            error=True,
        )
        extraction_runs = list(
            client.list_runs(
                project_name=project_name,
                start_time=start_time,
                is_root=True,
                tree_filter=_cv_certificate_trace_filter(),
                select=[
                    "id",
                    "name",
                    "run_type",
                    "start_time",
                    "end_time",
                    "error",
                    "status",
                    "total_tokens",
                    "total_cost",
                ],
                limit=50,
            )
        )
    except Exception as exc:  # pragma: no cover - exact SDK exceptions vary.
        raise LangSmithMonitoringError(f"Could not load LangSmith monitoring: {exc}") from exc

    return {
        "configured": True,
        "project_name": project_name,
        "dashboard_url": dashboard_url,
        "trace_view_label": CV_CERTIFICATE_TRACE_VIEW_LABEL,
        "trace_view_url": trace_view_url,
        "cv_extraction_dashboard_label": CV_EXTRACTION_DASHBOARD_TITLE,
        "cv_extraction_dashboard_url": cv_extraction_dashboard_url,
        "window_days": window_days,
        "totals": _totals_from_stats(stats, failed_stats),
        "cv_certificate_traces": [
            _run_summary(client, project_name, run)
            for run in extraction_runs
        ],
    }


def _cv_certificate_trace_filter() -> str:
    """Return a LangSmith filter for the CV/certificate trace view."""

    names = sorted(CV_CERTIFICATE_TRACE_NODE_NAMES)
    clauses = ", ".join(f'eq(name, "{name}")' for name in names)
    return f"or({clauses})"


def _cv_extraction_dashboard_url(
    *,
    client_factory: Callable[[], Any] | None,
) -> str:
    """Return the configured or discoverable LangSmith CV extraction dashboard URL."""

    configured_url = os.getenv("LANGSMITH_CV_EXTRACTION_DASHBOARD_URL", "").strip()
    if configured_url:
        return configured_url
    if client_factory is not None:
        return ""
    return _discover_custom_dashboard_url(CV_EXTRACTION_DASHBOARD_TITLE)


def _discover_custom_dashboard_url(title: str) -> str:
    """Look up one LangSmith custom chart section URL by exact title."""

    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        return ""

    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").strip()
    api_base = endpoint.rstrip("/")
    headers = {"x-api-key": api_key}
    try:
        sections_response = requests.get(
            f"{api_base}/charts/section",
            headers=headers,
            params={"title_contains": title, "limit": 10},
            timeout=10,
        )
        sections_response.raise_for_status()
        sections = sections_response.json()
        if not isinstance(sections, list):
            return ""
        section = next(
            (
                item
                for item in sections
                if isinstance(item, dict) and item.get("title") == title
            ),
            None,
        )
        section_id = str(section.get("id", "")).strip() if section else ""
        if not section_id:
            return ""

        workspaces_response = requests.get(
            f"{api_base}/workspaces",
            headers=headers,
            timeout=10,
        )
        workspaces_response.raise_for_status()
        workspaces = workspaces_response.json()
        if not isinstance(workspaces, list) or not workspaces:
            return ""
        workspace = next(
            (
                item
                for item in workspaces
                if isinstance(item, dict) and not item.get("is_deleted")
            ),
            None,
        )
        workspace_id = str(workspace.get("id", "")).strip() if workspace else ""
        if not workspace_id:
            return ""
    except Exception:
        return ""

    return f"{_langsmith_web_base_url(api_base)}/o/{workspace_id}/dashboards/{section_id}"


def _langsmith_web_base_url(api_base: str) -> str:
    """Convert a LangSmith API base URL to the matching web app base URL."""

    parsed = urlparse(api_base)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or parsed.path
    if host == "api.smith.langchain.com":
        host = "smith.langchain.com"
    elif host == "eu.api.smith.langchain.com":
        host = "eu.smith.langchain.com"
    elif host.startswith("api."):
        host = host.removeprefix("api.")
    return f"{scheme}://{host}".rstrip("/")


def _default_langsmith_client() -> Any:
    """Create a LangSmith client using the process environment."""

    from langsmith import Client

    return Client()


def _window_days(days: int) -> int:
    """Clamp requested monitoring windows to a small supported range."""

    return min(max(days, 1), 30)


def _empty_totals() -> dict[str, int | float | None]:
    """Return the zero-value metrics shape expected by the frontend."""

    return {
        "run_count": 0,
        "failed_run_count": 0,
        "error_rate": 0.0,
        "total_cost": 0.0,
        "total_tokens": 0,
        "latency_p50": None,
        "latency_p99": None,
    }


def _totals_from_stats(stats: dict[str, Any], failed_stats: dict[str, Any]) -> dict[str, Any]:
    """Normalize LangSmith aggregate stats into stable frontend fields."""

    run_count = int(stats.get("run_count") or 0)
    failed_run_count = int(failed_stats.get("run_count") or 0)
    raw_error_rate = stats.get("error_rate")
    error_rate = _number(raw_error_rate)
    if error_rate is None and run_count:
        error_rate = failed_run_count / run_count

    return {
        "run_count": run_count,
        "failed_run_count": failed_run_count,
        "error_rate": error_rate or 0.0,
        "total_cost": _number(stats.get("total_cost")) or 0.0,
        "total_tokens": int(stats.get("total_tokens") or 0),
        "latency_p50": _number(stats.get("latency_p50")),
        "latency_p99": _number(stats.get("latency_p99")),
    }


def _run_summary(client: Any, project_name: str, run: Any) -> dict[str, Any]:
    """Normalize one LangSmith run into table data."""

    run_url = ""
    try:
        run_url = client.get_run_url(run=run, project_name=project_name)
    except Exception:
        run_url = ""

    return {
        "id": str(_attr(run, "id", "")),
        "name": _attr(run, "name", "Untitled run"),
        "run_type": _attr(run, "run_type", ""),
        "start_time": _iso(_attr(run, "start_time", None)),
        "end_time": _iso(_attr(run, "end_time", None)),
        "status": _run_status(run),
        "error": _attr(run, "error", None),
        "total_tokens": int(_attr(run, "total_tokens", 0) or 0),
        "total_cost": _number(_attr(run, "total_cost", None)),
        "url": run_url,
    }


def _run_status(run: Any) -> str:
    """Return a small display status for a LangSmith run."""

    if _attr(run, "error", None):
        return "error"
    status = _attr(run, "status", "")
    if status:
        return str(status)
    if _attr(run, "end_time", None):
        return "complete"
    return "running"


def _attr(item: Any, name: str, default: Any = None) -> Any:
    """Read an attribute or dict key from SDK model-like objects."""

    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _iso(value: Any) -> str:
    """Return an ISO timestamp string for datetime-like values."""

    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _number(value: Any) -> float | None:
    """Convert LangSmith numeric values to JSON-safe floats."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
