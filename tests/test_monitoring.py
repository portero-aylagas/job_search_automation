from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.job_intake import create_job_listing
from src.monitoring import (
    LangSmithMonitoringError,
    LangSmithProvisioningError,
    _discover_custom_dashboard_url,
    compute_ai_quality_counters,
    langsmith_monitoring_summary,
    langsmith_provision_monitoring,
)
from src.schemas import (
    ApplicationArtifact,
    ApplicationFillBlockedField,
    ApplicationFillPlan,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
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
    assert [workflow["key"] for workflow in payload["workflows"]] == [
        "candidate_profile",
        "job_intake",
        "jobs",
        "karen",
        "browser_automation",
    ]
    assert payload["workflows"][0]["totals"]["run_count"] == 0
    assert payload["cv_certificate_traces"] == []


def test_ai_quality_counters_summarize_saved_models() -> None:
    job = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        job_details={
            "apply_url_resolution": {
                "manual_override": True,
                "manual_apply_url": "https://example.com/apply/automation-engineer",
            }
        },
    )
    requirements = ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status="blocked",
        job_preserving=False,
        blocked_reason="Apply page does not preserve the selected job.",
        required_documents=[
            ApplicationRequirementFinding(label="CV", required=True, confidence="high"),
            ApplicationRequirementFinding(
                label="Certificates",
                required=False,
                confidence="low",
            ),
        ],
        screening_questions=[
            ApplicationScreeningQuestion(
                question="Are you authorized to work in Germany?",
                required=True,
                confidence="low",
            )
        ],
        custom_form_fields=[
            ApplicationFormField(
                label="Portfolio URL",
                required=False,
                confidence="medium",
            )
        ],
        missing_or_uncertain=["Confirm earliest start date."],
        confidence="low",
    )
    package = ApplicationPackage(
        job_id=job.id,
        missing_information=[
            "Review generated artifact 'Cover Letter': unsupported claim.",
            "Candidate phone is missing.",
        ],
        artifacts=[
            ApplicationArtifact(
                id="answer-1",
                type="form_answer",
                label="Disability disclosure",
                content="No.",
                metadata={
                    "quality_findings": [
                        "Generated answer for a sensitive or user-decision field.",
                        "Claims experience with unsupported requirement: Kubernetes",
                    ]
                },
            )
        ],
    )
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        blocked_fields=[
            ApplicationFillBlockedField(
                label="Privacy consent",
                reason="Consent requires user review.",
            )
        ],
    )

    counters = compute_ai_quality_counters(
        job=job,
        requirements=requirements,
        package=package,
        fill_plan=fill_plan,
        apply_blockers=["Resolve reviewed application requirements before applying."],
    )

    assert counters.model_dump(mode="json") == {
        "generated_sensitive_user_decision_answers": 1,
        "unsupported_claim_findings": 1,
        "missing_information_count": 2,
        "missing_or_uncertain_requirements": 1,
        "low_confidence_requirements": 3,
        "manual_apply_url_override": 1,
        "blocked_requirements": 1,
        "blocked_apply_fields": 1,
        "apply_blockers": 1,
    }


def test_ai_quality_counters_return_zeroes_for_missing_artifacts() -> None:
    assert compute_ai_quality_counters().model_dump(mode="json") == {
        "generated_sensitive_user_decision_answers": 0,
        "unsupported_claim_findings": 0,
        "missing_information_count": 0,
        "missing_or_uncertain_requirements": 0,
        "low_confidence_requirements": 0,
        "manual_apply_url_override": 0,
        "blocked_requirements": 0,
        "blocked_apply_fields": 0,
        "apply_blockers": 0,
    }


def test_langsmith_monitoring_normalizes_stats_and_extraction_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")
    monkeypatch.setenv("LANGSMITH_DASHBOARD_URL", "https://smith.langchain.com/dashboards/1")
    monkeypatch.setenv(
        "LANGSMITH_MAIN_TRACES_URL",
        "https://smith.langchain.com/o/example/projects/p/traces?view=main",
    )
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
    assert (
        payload["main_trace_view_url"]
        == "https://smith.langchain.com/o/example/projects/p/traces?view=main"
    )
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
    candidate_profile = payload["workflows"][0]
    assert candidate_profile["key"] == "candidate_profile"
    assert candidate_profile["label"] == "Candidate Profile"
    assert candidate_profile["dashboard_label"] == "job-search-automation_cv-extraction"
    assert (
        candidate_profile["dashboard_url"]
        == "https://smith.langchain.com/o/example/dashboards/cv"
    )
    assert (
        candidate_profile["trace_view_url"]
        == "https://smith.langchain.com/o/example/projects/p/traces?view=cv"
    )
    assert candidate_profile["totals"]["run_count"] == 12
    assert candidate_profile["link_status_reason"] == ""
    assert len(candidate_profile["recent_runs"]) == 2
    assert candidate_profile["recent_runs"][0]["name"] == "Candidate Profile"
    assert payload["workflows"][1]["key"] == "job_intake"
    assert payload["workflows"][2]["key"] == "jobs"
    assert payload["workflows"][2]["label"] == "Jobs"
    assert payload["workflows"][2]["recent_runs"][0]["name"] == "Jobs"
    assert payload["workflows"][2]["recent_runs"][0]["metadata"][
        "workflow_subcategory_key"
    ] == "requirements"
    assert payload["workflows"][2]["recent_runs"][0]["metadata"][
        "workflow_subcategory_label"
    ] == "Requirements"
    assert payload["workflows"][2]["link_status_reason"] == "No dashboard configured"
    assert payload["workflow_cost_distribution"] == [
        {
            "key": "jobs",
            "label": "Jobs",
            "run_count": 2,
            "total_cost": 0.7,
            "total_tokens": 1900,
        },
        {
            "key": "unassigned",
            "label": "Unassigned",
            "run_count": 1,
            "total_cost": 0.2,
            "total_tokens": 500,
        },
    ]
    assert payload["job_costs"] == [
        {
            "key": "job-1",
            "label": "Example Co / Automation Engineer",
            "run_count": 2,
            "total_cost": 0.7,
            "total_tokens": 1900,
            "job_id": "job-1",
            "job_title": "Automation Engineer",
            "company": "Example Co",
        },
        {
            "key": "unassigned",
            "label": "Unassigned",
            "run_count": 1,
            "total_cost": 0.2,
            "total_tokens": 500,
            "job_id": "",
            "job_title": "",
            "company": "",
        },
    ]
    assert payload["cv_certificate_traces"] == [
        {
            "id": "run-1",
            "name": "Candidate Profile",
            "raw_name": "LangGraph",
            "run_type": "chain",
            "start_time": "2026-06-03T10:00:00+00:00",
            "end_time": "2026-06-03T10:00:02+00:00",
            "status": "complete",
            "error": None,
            "total_tokens": 400,
            "total_cost": 0.12,
            "tags": ["workflow:candidate_profile"],
            "metadata": {"workflow_key": "candidate_profile"},
            "url": "https://smith.langchain.com/r/run-1",
        },
        {
            "id": "run-2",
            "name": "LangGraph",
            "raw_name": "LangGraph",
            "run_type": "chain",
            "start_time": "2026-06-03T10:05:00+00:00",
            "end_time": "2026-06-03T10:05:02+00:00",
            "status": "complete",
            "error": None,
            "total_tokens": 250,
            "total_cost": 0.08,
            "tags": [],
            "metadata": {},
            "url": "https://smith.langchain.com/r/run-2",
        }
    ]
    assert client.stats_errors[:2] == [None, True]
    assert all(
        project_name == "job-search-automation"
        for project_name in client.list_project_names
    )
    assert client.list_tree_filters[0] == (
        'or(eq(name, "cv_extraction"), eq(name, "extract_cv_data"), '
        'eq(name, "inspect_cv_document_agent"), eq(name, "optional_document_extraction"))'
    )
    assert client.list_limits[-1] == 100
    assert 'eq(name, "job_extraction")' in client.list_tree_filters[2]
    assert 'eq(name, "application_requirements")' in client.list_tree_filters[3]
    assert 'eq(name, "application_package")' in client.list_tree_filters[3]
    assert 'eq(name, "application_field_mapping")' in client.list_tree_filters[3]


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


def test_langsmith_provision_monitoring_creates_workflow_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    client = FakeProvisionHttpClient()

    payload = langsmith_provision_monitoring(http_client=client)

    assert payload["configured"] is True
    assert payload["project_name"] == "job-search-automation"
    assert [workflow["key"] for workflow in payload["workflows"]] == [
        "candidate_profile",
        "job_intake",
        "jobs",
        "karen",
        "browser_automation",
    ]
    candidate_profile = payload["workflows"][0]
    assert candidate_profile["dashboard_label"] == "job-search-automation_cv-extraction"
    assert candidate_profile["dashboard_url"] == (
        "https://smith.langchain.com/o/workspace-1/dashboards/section-1"
    )
    assert "/projects/p/project-1/traces?" in candidate_profile["trace_view_url"]
    assert "cv_extraction" in candidate_profile["trace_view_url"]
    assert len(candidate_profile["chart_ids"]) == 3
    assert client.created_chart_payloads[0]["section_id"] == "section-1"
    assert client.created_chart_payloads[0]["filter"]["project_names"] == [
        "job-search-automation"
    ]
    assert any(
        payload["title"] == "Jobs errors"
        and "application_requirements" in payload["filter"]["tree_filter"]
        for payload in client.created_chart_payloads
    )


def test_langsmith_provision_monitoring_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "job-search-automation")

    with pytest.raises(LangSmithProvisioningError, match="LANGSMITH_API_KEY"):
        langsmith_provision_monitoring(http_client=FakeProvisionHttpClient())


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
        self.list_project_names: list[str] = []
        self.list_tree_filters: list[str] = []
        self.list_limits: list[int] = []

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
        self.list_project_names.append(str(kwargs.get("project_name")))
        self.list_tree_filters.append(str(kwargs.get("tree_filter")))
        self.list_limits.append(int(kwargs.get("limit") or 0))
        if kwargs.get("tree_filter") is None:
            return [
                SimpleNamespace(
                    id="cost-1",
                    name="LangGraph",
                    total_tokens=1000,
                    total_cost=0.4,
                    tags=["workflow:requirements"],
                    extra={
                        "metadata": {
                            "workflow_key": "jobs",
                            "workflow_subcategory_key": "requirements",
                            "workflow_subcategory_label": "Requirements",
                            "job_id": "job-1",
                            "job_title": "Automation Engineer",
                            "company": "Example Co",
                        }
                    },
                ),
                SimpleNamespace(
                    id="cost-2",
                    name="Application Package",
                    total_tokens=900,
                    total_cost=0.3,
                    tags=["workflow:application_package"],
                    extra={
                        "metadata": {
                            "workflow_key": "jobs",
                            "workflow_subcategory_key": "application_package",
                            "workflow_subcategory_label": "Application Package",
                            "job_id": "job-1",
                            "job_title": "Automation Engineer",
                            "company": "Example Co",
                        }
                    },
                ),
                SimpleNamespace(
                    id="cost-3",
                    name="LangGraph",
                    total_tokens=500,
                    total_cost=0.2,
                    tags=[],
                    extra={"metadata": {}},
                ),
            ]
        tree_filter = str(kwargs.get("tree_filter") or "")
        if "cv_extraction" in tree_filter:
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
                    tags=["workflow:candidate_profile"],
                    extra={"metadata": {"workflow_key": "candidate_profile"}},
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
                    tags=[],
                    extra={"metadata": {}},
                ),
            ]
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
                tags=["workflow:jobs"],
                extra={
                    "metadata": {
                        "workflow_key": "jobs",
                        "workflow_subcategory_key": "requirements",
                        "workflow_subcategory_label": "Requirements",
                    }
                },
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
                tags=[],
                extra={"metadata": {}},
            )
        ]

    def get_run_url(self, *, run: SimpleNamespace, project_name: str) -> str:
        return f"https://smith.langchain.com/r/{run.id}"


class BrokenLangSmithClient:
    def get_run_stats(self, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("network unavailable")


class FakeProvisionHttpClient:
    def __init__(self) -> None:
        self.created_chart_payloads: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        if url.endswith("/workspaces"):
            return FakeResponse([{"id": "workspace-1", "is_deleted": False}])
        if url.endswith("/sessions"):
            return FakeResponse([{"id": "project-1", "name": "job-search-automation"}])
        if url.endswith("/charts/section"):
            return FakeResponse([])
        if url.endswith("/charts"):
            return FakeResponse([])
        raise AssertionError(f"Unexpected GET URL: {url}")

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        if url.endswith("/charts/section"):
            return FakeResponse({"id": "section-1", "title": kwargs["json"]["title"]})
        if url.endswith("/charts"):
            payload = kwargs["json"]
            self.created_chart_payloads.append(payload)
            return FakeResponse({"id": f"chart-{len(self.created_chart_payloads)}"})
        raise AssertionError(f"Unexpected POST URL: {url}")

    def patch(self, url: str, **kwargs: object) -> FakeResponse:
        raise AssertionError(f"Unexpected PATCH URL: {url}")
