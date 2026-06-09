"""LangSmith monitoring summaries for the React Monitoring tab."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests

from src.schemas import (
    AIQualityCounters,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    JobListing,
)

CV_EXTRACTION_DASHBOARD_TITLE = "job-search-automation_cv-extraction"
CV_CERTIFICATE_TRACE_NODE_NAMES = {
    "cv_extraction",
    "extract_cv_data",
    "inspect_cv_document_agent",
    "optional_document_extraction",
}
CV_CERTIFICATE_TRACE_VIEW_LABEL = "CV & Certificates Extraction"
GENERIC_ROOT_NAMES = {"langgraph", "browser use", "browser_use", "browseruse"}
UNASSIGNED_LABEL = "Unassigned"
JOB_WORKFLOW_SUBCATEGORIES = {
    "apply_url_ranking": "Apply URL Ranking",
    "requirements": "Requirements",
    "application_package": "Application Package",
    "field_mapping": "Field Mapping",
}
JOB_WORKFLOW_NODE_NAMES = (
    "AI apply URL ranking",
    "AI application field mapping",
    "AI application requirements extraction",
    "AI package generation",
    "application_field_mapping",
    "application_package",
    "application_requirements",
    "apply_url_ranking",
)


@dataclass(frozen=True)
class LangSmithWorkflow:
    """LangSmith workflow group shown on the Monitoring page."""

    key: str
    label: str
    description: str
    node_names: tuple[str, ...]
    dashboard_title: str = ""
    trace_view_env: str = ""
    dashboard_env: str = ""


LANGSMITH_WORKFLOWS = (
    LangSmithWorkflow(
        key="candidate_profile",
        label="Candidate Profile",
        description="CV and optional supporting-document extraction.",
        node_names=tuple(sorted(CV_CERTIFICATE_TRACE_NODE_NAMES)),
        dashboard_title=CV_EXTRACTION_DASHBOARD_TITLE,
        trace_view_env="LANGSMITH_CV_CERTIFICATES_TRACE_VIEW_URL",
        dashboard_env="LANGSMITH_CV_EXTRACTION_DASHBOARD_URL",
    ),
    LangSmithWorkflow(
        key="job_intake",
        label="Job Intake",
        description="Job posting extraction and apply-link resolution.",
        node_names=(
            "AI apply URL resolution",
            "AI job extraction",
            "apply_url_resolution",
            "job_extraction",
        ),
    ),
    LangSmithWorkflow(
        key="jobs",
        label="Jobs",
        description="Apply URL ranking, requirements, package generation, and field mapping.",
        node_names=JOB_WORKFLOW_NODE_NAMES,
    ),
    LangSmithWorkflow(
        key="karen",
        label="Karen",
        description="Agent intent classification and workflow routing.",
        node_names=("Karen intent classification", "karen_intent"),
    ),
    LangSmithWorkflow(
        key="browser_automation",
        label="Browser Automation",
        description="Browser Use apply-agent traces.",
        node_names=("browser_use_apply_agent",),
    ),
)


class LangSmithMonitoringError(RuntimeError):
    """Raised when LangSmith monitoring data cannot be loaded."""


class LangSmithProvisioningError(RuntimeError):
    """Raised when LangSmith dashboard provisioning cannot complete."""


def compute_ai_quality_counters(
    *,
    job: JobListing | None = None,
    requirements: ApplicationRequirements | None = None,
    package: ApplicationPackage | None = None,
    fill_plan: ApplicationFillPlan | None = None,
    apply_blockers: list[str] | None = None,
) -> AIQualityCounters:
    """Return deterministic quality counters from already-saved workflow models."""

    counters = AIQualityCounters()
    if package is not None:
        counters.missing_information_count = len(package.missing_information)
        for artifact in package.artifacts:
            for finding in _artifact_quality_findings(artifact.metadata):
                normalized = finding.casefold()
                if "sensitive or user-decision" in normalized:
                    counters.generated_sensitive_user_decision_answers += 1
                if normalized.startswith(
                    "claims experience with unsupported requirement:"
                ):
                    counters.unsupported_claim_findings += 1

    if requirements is not None:
        counters.missing_or_uncertain_requirements = len(requirements.missing_or_uncertain)
        counters.low_confidence_requirements = _low_confidence_requirement_count(
            requirements,
        )
        if requirements.status == "blocked" or not requirements.job_preserving:
            counters.blocked_requirements = 1

    if job is not None and _manual_apply_url_override(job):
        counters.manual_apply_url_override = 1

    if fill_plan is not None:
        counters.blocked_apply_fields = len(fill_plan.blocked_fields)

    counters.apply_blockers = len(apply_blockers or [])
    return counters


def langsmith_provision_monitoring(
    *,
    http_client: Any = requests,
) -> dict[str, Any]:
    """Create or update LangSmith dashboard links for monitored workflows.

    This intentionally runs only from the explicit provisioning endpoint. The
    read-only monitoring summary may discover already-configured URLs, but it
    does not mutate LangSmith resources.
    """

    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    project_name = os.getenv("LANGSMITH_PROJECT", "").strip()
    if not api_key or not project_name:
        raise LangSmithProvisioningError(
            "Set LANGSMITH_API_KEY and LANGSMITH_PROJECT before provisioning LangSmith dashboards."
        )

    api_base = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").strip().rstrip("/")
    headers = {"x-api-key": api_key, "content-type": "application/json"}
    workspace_id = _active_workspace_id(api_base, headers, http_client=http_client)
    project_id = _project_id(api_base, headers, project_name, http_client=http_client)

    workflows: list[dict[str, Any]] = []
    for workflow in LANGSMITH_WORKFLOWS:
        section_title = _provisioned_dashboard_title(workflow)
        section = _upsert_dashboard_section(
            api_base,
            headers,
            section_title,
            http_client=http_client,
        )
        section_id = str(section.get("id", "")).strip()
        chart_ids = _upsert_workflow_charts(
            api_base,
            headers,
            section_id,
            workflow,
            project_name,
            http_client=http_client,
        )
        trace_view_url = _workflow_project_trace_url(
            api_base,
            workspace_id=workspace_id,
            project_id=project_id,
            workflow=workflow,
        )
        workflows.append(
            {
                "key": workflow.key,
                "label": workflow.label,
                "dashboard_label": section_title,
                "dashboard_url": _dashboard_url(api_base, workspace_id, section_id),
                "trace_view_url": trace_view_url,
                "section_id": section_id,
                "chart_ids": chart_ids,
                "link_status_reason": "",
            }
        )

    return {
        "configured": True,
        "project_name": project_name,
        "workflows": workflows,
        "message": "LangSmith workflow dashboards and trace links were provisioned.",
    }


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
    main_trace_view_url = os.getenv("LANGSMITH_MAIN_TRACES_URL", "").strip()
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
            "main_trace_view_url": main_trace_view_url,
            "trace_view_label": CV_CERTIFICATE_TRACE_VIEW_LABEL,
            "trace_view_url": trace_view_url,
            "cv_extraction_dashboard_label": CV_EXTRACTION_DASHBOARD_TITLE,
            "cv_extraction_dashboard_url": cv_extraction_dashboard_url,
            "window_days": window_days,
            "totals": _empty_totals(),
            "workflows": _empty_workflow_summaries(),
            "cv_certificate_traces": [],
            "workflow_cost_distribution": [],
            "job_costs": [],
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
                    "tags",
                    "extra",
                ],
                limit=50,
            )
        )
        workflows = [
            _workflow_summary(client, project_name, start_time, workflow)
            for workflow in LANGSMITH_WORKFLOWS
        ]
        cost_runs = list(
            client.list_runs(
                project_name=project_name,
                start_time=start_time,
                is_root=True,
                select=[
                    "id",
                    "name",
                    "total_tokens",
                    "total_cost",
                    "tags",
                    "extra",
                ],
                limit=100,
            )
        )
    except Exception as exc:  # pragma: no cover - exact SDK exceptions vary.
        raise LangSmithMonitoringError(f"Could not load LangSmith monitoring: {exc}") from exc

    return {
        "configured": True,
        "project_name": project_name,
        "dashboard_url": dashboard_url,
        "main_trace_view_url": main_trace_view_url,
        "trace_view_label": CV_CERTIFICATE_TRACE_VIEW_LABEL,
        "trace_view_url": trace_view_url,
        "cv_extraction_dashboard_label": CV_EXTRACTION_DASHBOARD_TITLE,
        "cv_extraction_dashboard_url": cv_extraction_dashboard_url,
        "window_days": window_days,
        "totals": _totals_from_stats(stats, failed_stats),
        "workflows": workflows,
        "cv_certificate_traces": [
            _run_summary(client, project_name, run)
            for run in extraction_runs
        ],
        "workflow_cost_distribution": _workflow_cost_distribution(cost_runs),
        "job_costs": _job_cost_distribution(cost_runs),
    }


def _cv_certificate_trace_filter() -> str:
    """Return a LangSmith filter for the CV/certificate trace view."""

    return _trace_filter(CV_CERTIFICATE_TRACE_NODE_NAMES)


def _trace_filter(node_names: tuple[str, ...] | set[str]) -> str:
    """Return a LangSmith tree filter matching any of the given run names."""

    names = sorted(node_names)
    clauses = ", ".join(f'eq(name, "{name}")' for name in names)
    if len(names) == 1:
        return clauses
    return f"or({clauses})"


def _artifact_quality_findings(metadata: dict[str, Any]) -> list[str]:
    raw_findings = metadata.get("quality_findings", [])
    if isinstance(raw_findings, str):
        return [raw_findings.strip()] if raw_findings.strip() else []
    if not isinstance(raw_findings, list):
        return []
    return [str(item).strip() for item in raw_findings if str(item).strip()]


def _low_confidence_requirement_count(requirements: ApplicationRequirements) -> int:
    count = 1 if requirements.confidence == "low" else 0
    findings = [
        *requirements.required_documents,
        *requirements.upload_expectations,
        *requirements.consent_requirements,
        *requirements.privacy_login_ats_gates,
        *requirements.deadlines,
        *requirements.contact_or_fallback,
    ]
    if requirements.motivation_letter is not None:
        findings.append(requirements.motivation_letter)
    count += sum(1 for finding in findings if finding.confidence == "low")
    count += sum(
        1
        for question in requirements.screening_questions
        if question.confidence == "low"
    )
    count += sum(
        1
        for field in [*requirements.custom_form_fields, *requirements.profile_fields]
        if field.confidence == "low"
    )
    return count


def _manual_apply_url_override(job: JobListing) -> bool:
    resolution = job.job_details.get("apply_url_resolution", {})
    return isinstance(resolution, dict) and bool(resolution.get("manual_override"))


def _empty_workflow_summaries() -> list[dict[str, Any]]:
    """Return configured workflow metadata with empty metrics."""

    return [
        {
            "key": workflow.key,
            "label": workflow.label,
            "description": workflow.description,
            "trace_view_url": _workflow_trace_view_url(workflow, ""),
            "dashboard_label": workflow.dashboard_title,
            "dashboard_url": _workflow_dashboard_url(workflow, client_factory=None),
            "link_status_reason": _workflow_link_status_reason(
                _workflow_trace_view_url(workflow, ""),
                _workflow_dashboard_url(workflow, client_factory=None),
            ),
            "totals": _empty_totals(),
            "recent_runs": [],
        }
        for workflow in LANGSMITH_WORKFLOWS
    ]


def _workflow_summary(
    client: Any,
    project_name: str,
    start_time: datetime,
    workflow: LangSmithWorkflow,
) -> dict[str, Any]:
    """Return LangSmith stats and recent traces for one workflow group."""

    tree_filter = _trace_filter(workflow.node_names)
    stats = _workflow_run_stats(
        client,
        project_name=project_name,
        start_time=start_time,
        tree_filter=tree_filter,
    )
    failed_stats = _workflow_run_stats(
        client,
        project_name=project_name,
        start_time=start_time,
        tree_filter=tree_filter,
        error=True,
    )
    runs = list(
        client.list_runs(
            project_name=project_name,
            start_time=start_time,
            is_root=True,
            tree_filter=tree_filter,
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
                "tags",
                "extra",
            ],
            limit=10,
        )
    )
    return {
        "key": workflow.key,
        "label": workflow.label,
        "description": workflow.description,
        "trace_view_url": _workflow_trace_view_url(
            workflow,
            os.getenv("LANGSMITH_DASHBOARD_URL", ""),
        ),
        "dashboard_label": workflow.dashboard_title,
        "dashboard_url": _workflow_dashboard_url(workflow, client_factory=None),
        "link_status_reason": _workflow_link_status_reason(
            _workflow_trace_view_url(
                workflow,
                os.getenv("LANGSMITH_DASHBOARD_URL", ""),
            ),
            _workflow_dashboard_url(workflow, client_factory=None),
        ),
        "totals": _totals_from_stats(stats, failed_stats),
        "recent_runs": [_run_summary(client, project_name, run, workflow=workflow) for run in runs],
    }


def _workflow_link_status_reason(trace_view_url: str, dashboard_url: str) -> str:
    """Return a short reason when workflow links are not configured."""

    if trace_view_url or dashboard_url:
        if not dashboard_url:
            return "No dashboard configured"
        if not trace_view_url:
            return "No trace view configured"
        return ""
    return "No dashboard configured"


def _workflow_run_stats(
    client: Any,
    *,
    project_name: str,
    start_time: datetime,
    tree_filter: str,
    error: bool | None = None,
) -> dict[str, Any]:
    """Load workflow-specific stats, falling back when SDKs lack tree filters."""

    kwargs: dict[str, Any] = {
        "project_names": [project_name],
        "start_time": start_time.isoformat(),
        "is_root": True,
        "tree_filter": tree_filter,
    }
    if error is not None:
        kwargs["error"] = error
    try:
        return client.get_run_stats(**kwargs)
    except TypeError:
        return _empty_totals()


def _workflow_trace_view_url(workflow: LangSmithWorkflow, default_url: str) -> str:
    """Return the configured trace view URL for a workflow."""

    if workflow.trace_view_env:
        return os.getenv(workflow.trace_view_env, "").strip() or default_url
    return ""


def _workflow_dashboard_url(
    workflow: LangSmithWorkflow,
    *,
    client_factory: Callable[[], Any] | None,
) -> str:
    """Return a workflow-specific custom dashboard URL when configured."""

    if workflow.dashboard_env:
        configured_url = os.getenv(workflow.dashboard_env, "").strip()
        if configured_url:
            return configured_url
    if not workflow.dashboard_title or client_factory is not None:
        return ""
    return _discover_custom_dashboard_url(workflow.dashboard_title)


def _cv_extraction_dashboard_url(
    *,
    client_factory: Callable[[], Any] | None,
) -> str:
    """Return the configured or discoverable LangSmith CV extraction dashboard URL."""

    return _workflow_dashboard_url(LANGSMITH_WORKFLOWS[0], client_factory=client_factory)


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


def _active_workspace_id(
    api_base: str,
    headers: dict[str, str],
    *,
    http_client: Any,
) -> str:
    response = http_client.get(f"{api_base}/workspaces", headers=headers, timeout=10)
    response.raise_for_status()
    workspaces = response.json()
    if not isinstance(workspaces, list):
        raise LangSmithProvisioningError("LangSmith workspaces response was not a list.")
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
        raise LangSmithProvisioningError("Could not find an active LangSmith workspace.")
    return workspace_id


def _project_id(
    api_base: str,
    headers: dict[str, str],
    project_name: str,
    *,
    http_client: Any,
) -> str:
    response = http_client.get(
        f"{api_base}/sessions",
        headers=headers,
        params={"name": project_name, "limit": 1},
        timeout=10,
    )
    response.raise_for_status()
    projects = response.json()
    if isinstance(projects, dict):
        projects = projects.get("sessions", projects.get("items", []))
    if not isinstance(projects, list):
        raise LangSmithProvisioningError("LangSmith projects response was not a list.")
    project = next(
        (
            item
            for item in projects
            if isinstance(item, dict) and item.get("name") == project_name
        ),
        projects[0] if projects else None,
    )
    project_id = str(project.get("id", "")).strip() if project else ""
    if not project_id:
        raise LangSmithProvisioningError(
            f"Could not find LangSmith project {project_name!r}."
        )
    return project_id


def _upsert_dashboard_section(
    api_base: str,
    headers: dict[str, str],
    title: str,
    *,
    http_client: Any,
) -> dict[str, Any]:
    response = http_client.get(
        f"{api_base}/charts/section",
        headers=headers,
        params={"title_contains": title, "limit": 10},
        timeout=10,
    )
    response.raise_for_status()
    sections = response.json()
    if isinstance(sections, list):
        section = next(
            (
                item
                for item in sections
                if isinstance(item, dict) and item.get("title") == title
            ),
            None,
        )
        if section:
            section_id = str(section.get("id", "")).strip()
            if section_id:
                patch_response = http_client.patch(
                    f"{api_base}/charts/section/{section_id}",
                    headers=headers,
                    json={"title": title},
                    timeout=10,
                )
                patch_response.raise_for_status()
                patched = patch_response.json()
                return patched if isinstance(patched, dict) else section

    create_response = http_client.post(
        f"{api_base}/charts/section",
        headers=headers,
        json={"title": title},
        timeout=10,
    )
    create_response.raise_for_status()
    created = create_response.json()
    if not isinstance(created, dict) or not str(created.get("id", "")).strip():
        raise LangSmithProvisioningError(f"Could not create dashboard section {title!r}.")
    return created


def _upsert_workflow_charts(
    api_base: str,
    headers: dict[str, str],
    section_id: str,
    workflow: LangSmithWorkflow,
    project_name: str,
    *,
    http_client: Any,
) -> list[str]:
    chart_ids: list[str] = []
    existing_charts = _dashboard_section_charts(
        api_base,
        headers,
        section_id,
        http_client=http_client,
    )
    for chart in _workflow_chart_payloads(workflow, project_name):
        payload = {**chart, "section_id": section_id}
        existing = next(
            (
                item
                for item in existing_charts
                if isinstance(item, dict) and item.get("title") == payload["title"]
            ),
            None,
        )
        chart_id = str(existing.get("id", "")).strip() if existing else ""
        if chart_id:
            response = http_client.patch(
                f"{api_base}/charts/{chart_id}",
                headers=headers,
                json=payload,
                timeout=10,
            )
        else:
            response = http_client.post(
                f"{api_base}/charts",
                headers=headers,
                json=payload,
                timeout=10,
            )
        response.raise_for_status()
        saved = response.json()
        if isinstance(saved, dict) and saved.get("id"):
            chart_ids.append(str(saved["id"]))
    return chart_ids


def _dashboard_section_charts(
    api_base: str,
    headers: dict[str, str],
    section_id: str,
    *,
    http_client: Any,
) -> list[dict[str, Any]]:
    response = http_client.get(
        f"{api_base}/charts",
        headers=headers,
        params={"section_id": section_id, "limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    charts = response.json()
    return charts if isinstance(charts, list) else []


def _workflow_chart_payloads(
    workflow: LangSmithWorkflow,
    project_name: str,
) -> list[dict[str, Any]]:
    tree_filter = _trace_filter(workflow.node_names)
    base_filter = {
        "project_names": [project_name],
        "is_root": True,
        "tree_filter": tree_filter,
    }
    return [
        {
            "title": f"{workflow.label} runs",
            "chart_type": "timeseries",
            "metric": "run_count",
            "filter": base_filter,
        },
        {
            "title": f"{workflow.label} cost",
            "chart_type": "timeseries",
            "metric": "total_cost",
            "filter": base_filter,
        },
        {
            "title": f"{workflow.label} errors",
            "chart_type": "timeseries",
            "metric": "error_rate",
            "filter": base_filter,
        },
    ]


def _provisioned_dashboard_title(workflow: LangSmithWorkflow) -> str:
    if workflow.dashboard_title:
        return workflow.dashboard_title
    return f"job-search-automation_{workflow.key.replace('_', '-')}"


def _dashboard_url(api_base: str, workspace_id: str, section_id: str) -> str:
    if not workspace_id or not section_id:
        return ""
    return f"{_langsmith_web_base_url(api_base)}/o/{workspace_id}/dashboards/{section_id}"


def _workflow_project_trace_url(
    api_base: str,
    *,
    workspace_id: str,
    project_id: str,
    workflow: LangSmithWorkflow,
) -> str:
    if not workspace_id or not project_id:
        return ""
    query = urlencode({"filter": _trace_filter(workflow.node_names)})
    return (
        f"{_langsmith_web_base_url(api_base)}/o/{workspace_id}/projects/p/"
        f"{quote(project_id)}/traces?{query}"
    )


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


def _run_summary(
    client: Any,
    project_name: str,
    run: Any,
    *,
    workflow: LangSmithWorkflow | None = None,
) -> dict[str, Any]:
    """Normalize one LangSmith run into table data."""

    run_url = ""
    try:
        run_url = client.get_run_url(run=run, project_name=project_name)
    except Exception:
        run_url = ""

    metadata = _run_metadata(run)
    tags = _run_tags(run)
    raw_name = str(_attr(run, "name", "Untitled run") or "Untitled run")

    return {
        "id": str(_attr(run, "id", "")),
        "name": _display_run_name(raw_name, metadata, workflow),
        "raw_name": raw_name,
        "run_type": _attr(run, "run_type", ""),
        "start_time": _iso(_attr(run, "start_time", None)),
        "end_time": _iso(_attr(run, "end_time", None)),
        "status": _run_status(run),
        "error": _attr(run, "error", None),
        "total_tokens": int(_attr(run, "total_tokens", 0) or 0),
        "total_cost": _number(_attr(run, "total_cost", None)),
        "tags": tags,
        "metadata": metadata,
        "url": run_url,
    }


def _display_run_name(
    raw_name: str,
    metadata: dict[str, Any],
    workflow: LangSmithWorkflow | None,
) -> str:
    """Return a useful display name for generic LangSmith root runs."""

    configured_name = str(metadata.get("display_name") or "").strip()
    if configured_name:
        return configured_name
    normalized_name = raw_name.strip().casefold()
    if normalized_name not in GENERIC_ROOT_NAMES:
        return raw_name
    if workflow is not None:
        return workflow.label
    workflow_key = _visible_workflow_key(str(metadata.get("workflow_key") or "").strip())
    matched_workflow = _workflow_by_key(workflow_key)
    if matched_workflow is not None:
        return matched_workflow.label
    return raw_name


def _workflow_by_key(workflow_key: str) -> LangSmithWorkflow | None:
    """Return configured workflow metadata for a workflow key."""

    return next(
        (workflow for workflow in LANGSMITH_WORKFLOWS if workflow.key == workflow_key),
        None,
    )


def _workflow_cost_distribution(runs: list[Any]) -> list[dict[str, Any]]:
    """Return total cost grouped by workflow metadata, with unassigned runs retained."""

    groups: dict[str, dict[str, Any]] = {}
    for run in runs:
        workflow_key = _workflow_key_for_run(run)
        workflow = _workflow_by_key(workflow_key)
        key = workflow.key if workflow is not None else workflow_key or "unassigned"
        label = workflow.label if workflow is not None else UNASSIGNED_LABEL
        _add_cost(groups, key=key, label=label, run=run)
    return _sorted_cost_groups(groups)


def _job_cost_distribution(runs: list[Any]) -> list[dict[str, Any]]:
    """Return total cost grouped by job metadata, with old traces retained."""

    groups: dict[str, dict[str, Any]] = {}
    for run in runs:
        metadata = _run_metadata(run)
        job_id = str(metadata.get("job_id") or "").strip()
        job_title = str(metadata.get("job_title") or "").strip()
        company = str(metadata.get("company") or "").strip()
        if job_id or job_title or company:
            label = " / ".join(item for item in (company, job_title) if item) or job_id
            key = job_id or label
        else:
            label = UNASSIGNED_LABEL
            key = "unassigned"
        _add_cost(
            groups,
            key=key,
            label=label,
            run=run,
            extra={"job_id": job_id, "job_title": job_title, "company": company},
        )
    return _sorted_cost_groups(groups)


def _workflow_key_for_run(run: Any) -> str:
    """Return the workflow key from metadata, tags, or known run names."""

    metadata = _run_metadata(run)
    workflow_key = str(metadata.get("workflow_key") or "").strip()
    if workflow_key:
        return _visible_workflow_key(workflow_key)
    tags = _run_tags(run)
    for tag in tags:
        if tag.startswith("workflow:"):
            return _visible_workflow_key(tag.removeprefix("workflow:"))
    run_name = str(_attr(run, "name", "") or "")
    for workflow in LANGSMITH_WORKFLOWS:
        if run_name in workflow.node_names or run_name == workflow.label:
            return workflow.key
    return ""


def _visible_workflow_key(workflow_key: str) -> str:
    """Return the visible monitoring workflow for current and legacy keys."""

    return "jobs" if workflow_key in JOB_WORKFLOW_SUBCATEGORIES else workflow_key


def _add_cost(
    groups: dict[str, dict[str, Any]],
    *,
    key: str,
    label: str,
    run: Any,
    extra: dict[str, Any] | None = None,
) -> None:
    """Accumulate run cost data into a group."""

    group = groups.setdefault(
        key,
        {
            "key": key,
            "label": label,
            "run_count": 0,
            "total_cost": 0.0,
            "total_tokens": 0,
            **(extra or {}),
        },
    )
    group["run_count"] += 1
    group["total_cost"] += _number(_attr(run, "total_cost", None)) or 0.0
    group["total_tokens"] += int(_attr(run, "total_tokens", 0) or 0)


def _sorted_cost_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cost groups ordered by cost, keeping Unassigned visible."""

    return sorted(
        groups.values(),
        key=lambda item: (item["label"] == UNASSIGNED_LABEL, -float(item["total_cost"])),
    )


def _run_metadata(run: Any) -> dict[str, Any]:
    """Return LangSmith run metadata from common SDK shapes."""

    direct_metadata = _attr(run, "metadata", None)
    if isinstance(direct_metadata, dict):
        return direct_metadata
    extra = _attr(run, "extra", {})
    if isinstance(extra, dict):
        metadata = extra.get("metadata", {})
        if isinstance(metadata, dict):
            return metadata
    return {}


def _run_tags(run: Any) -> list[str]:
    """Return normalized LangSmith run tags."""

    tags = _attr(run, "tags", [])
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags if str(tag).strip()]


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
