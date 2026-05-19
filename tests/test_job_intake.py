from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.job_intake import (
    choose_valid_apply_url,
    create_job_listing,
    persist_job_listing,
    validate_apply_url,
)
from src.llm_job_extraction import (
    ApplyUrlResolution,
    ExtractedJobData,
    build_job_page_snapshot,
    extract_job_data_with_llm,
    extract_job_data_with_web_search_fallback,
    resolve_apply_url_from_snapshot,
    run_job_intake_graph,
    save_job_page_snapshot,
)
from src.schemas import JobListing, JobPageSnapshot, TrackerRecord
from src.storage import load_model


def test_persist_job_listing_creates_job_folder_and_normalized_json(tmp_path: Path) -> None:
    job_listing = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        location="Berlin",
        remote_policy="Hybrid",
        apply_url="https://example.com/apply",
        description="Build internal tools and automate reporting workflows.",
        now=datetime(2026, 5, 19, 12, 30, tzinfo=timezone.utc),
    )

    job_path = persist_job_listing(tmp_path, job_listing)
    saved_listing = load_model(job_path, JobListing)

    assert job_path == (
        tmp_path
        / "data"
        / "runtime"
        / "jobs"
        / "job-20260519123000-example-co-automation-engineer"
        / "normalized_job.json"
    )
    assert saved_listing == job_listing
    assert job_path.parent.is_dir()


def test_persist_job_listing_appends_new_tracker_record(tmp_path: Path) -> None:
    first_job = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        location="Berlin",
        remote_policy="Hybrid",
        apply_url="https://example.com/apply",
        description="Build internal tools and automate reporting workflows.",
        now=datetime(2026, 5, 19, 12, 30, tzinfo=timezone.utc),
    )
    second_job = create_job_listing(
        title="Data Analyst",
        company="Harbor Metrics",
        source_url="https://example.com/jobs/data-analyst",
        now=datetime(2026, 5, 19, 12, 31, tzinfo=timezone.utc),
    )

    persist_job_listing(tmp_path, first_job)
    persist_job_listing(tmp_path, second_job)
    tracker_records = load_model(
        tmp_path / "data" / "runtime" / "jobs.json",
        list[TrackerRecord],
    )

    assert len(tracker_records) == 2
    assert tracker_records[0].job_id == first_job.id
    assert tracker_records[0].status == "new"
    assert tracker_records[1].job_id == second_job.id
    assert str(tracker_records[1].source_url) == "https://example.com/jobs/data-analyst"
    assert tracker_records[1].retrieval_mode == "url"


def test_create_job_listing_requires_only_visible_core_fields() -> None:
    job_listing = create_job_listing(
        title="Data Analyst",
        company="Harbor Metrics",
        source_url="https://example.com/jobs/data-analyst",
        now=datetime(2026, 5, 19, 12, 31, tzinfo=timezone.utc),
    )

    assert job_listing.title == "Data Analyst"
    assert job_listing.company == "Harbor Metrics"
    assert str(job_listing.source_url) == "https://example.com/jobs/data-analyst"
    assert job_listing.location is None
    assert job_listing.description is None
    assert job_listing.retrieval_mode == "url"


def test_create_job_listing_rejects_blank_required_fields() -> None:
    with pytest.raises(ValueError, match="Title is required."):
        create_job_listing(
            title=" ",
            company="Example Co",
            source_url="https://example.com/jobs/automation-engineer",
        )


def test_create_job_listing_rejects_blank_source_url() -> None:
    with pytest.raises(ValueError, match="Job URL is required."):
        create_job_listing(
            title="Automation Engineer",
            company="Example Co",
            source_url=" ",
        )


def test_validate_apply_url_rejects_blank_value() -> None:
    with pytest.raises(
        ValueError,
        match="Apply URL is required before the workflow can continue.",
    ):
        validate_apply_url(" ", "https://example.com/jobs/automation-engineer")


def test_validate_apply_url_rejects_apply_url_that_matches_source_url() -> None:
    with pytest.raises(
        ValueError,
        match="Apply URL must point to the application destination, not the job offer page.",
    ):
        validate_apply_url(
            "https://example.com/jobs/automation-engineer/",
            "https://example.com/jobs/automation-engineer",
        )


def test_create_job_listing_accepts_distinct_apply_url() -> None:
    job_listing = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
    )

    assert str(job_listing.apply_url) == "https://example.com/apply/automation-engineer"


def test_choose_valid_apply_url_prefers_distinct_http_url() -> None:
    chosen = choose_valid_apply_url(
        "https://example.com/jobs/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        "mailto:jobs@example.com",
        "https://example.com/apply/automation-engineer",
    )

    assert chosen == "https://example.com/apply/automation-engineer"


def test_choose_valid_apply_url_returns_empty_when_all_candidates_are_invalid() -> None:
    chosen = choose_valid_apply_url(
        "https://example.com/jobs/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        "mailto:jobs@example.com",
    )

    assert chosen == ""


def make_job_snapshot() -> JobPageSnapshot:
    return build_job_page_snapshot(
        requested_url="https://example.com/jobs/automation-engineer",
        final_url="https://example.com/jobs/automation-engineer",
        html="""
        <html><head><title>Automation Engineer</title></head><body>
          <h1>Automation Engineer</h1>
          <p>Example Co builds automation tools.</p>
          <a href="/jobs/automation-engineer/apply">Apply now</a>
        </body></html>
        """,
        fetch_status=200,
        content_type="text/html",
    )


def test_job_intake_graph_invokes_inspection_before_extraction_and_resolution() -> None:
    calls = []
    snapshot = make_job_snapshot()

    def fake_inspector(source_url: str) -> JobPageSnapshot:
        calls.append("inspect_job_page_agent")
        assert source_url == "https://example.com/jobs/automation-engineer"
        return snapshot

    def fake_extractor(source_url: str, received_snapshot: JobPageSnapshot) -> ExtractedJobData:
        calls.append("extract_job_data")
        assert source_url == "https://example.com/jobs/automation-engineer"
        assert received_snapshot is snapshot
        return ExtractedJobData(title="Automation Engineer", company="Example Co")

    def fake_resolver(
        source_url: str,
        received_snapshot: JobPageSnapshot,
        extracted: ExtractedJobData,
    ) -> ApplyUrlResolution:
        calls.append("resolve_apply_url")
        assert received_snapshot is snapshot
        assert extracted.title == "Automation Engineer"
        return ApplyUrlResolution(
            status="resolved",
            apply_url="https://example.com/jobs/automation-engineer/apply",
            confidence="high",
        )

    state = run_job_intake_graph(
        "https://example.com/jobs/automation-engineer",
        inspector=fake_inspector,
        extractor=fake_extractor,
        apply_resolver=fake_resolver,
    )

    assert calls == ["inspect_job_page_agent", "extract_job_data", "resolve_apply_url"]
    assert state["extraction_mode"] == "snapshot"
    assert state["extracted_job_data"].apply_url == "https://example.com/jobs/automation-engineer/apply"


def test_snapshot_llm_extractor_does_not_list_web_search(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(
                output_parsed=ExtractedJobData(
                    title="Automation Engineer",
                    company="Example Co",
                )
            )

    monkeypatch.setattr(
        "src.llm_job_extraction._get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    extracted = extract_job_data_with_llm(
        "https://example.com/jobs/automation-engineer",
        make_job_snapshot(),
    )

    assert extracted.title == "Automation Engineer"
    assert "tools" not in parse_calls[0]
    assert "tool_choice" not in parse_calls[0]


def test_fallback_extractor_lists_web_search(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(
                output_parsed=ExtractedJobData(
                    title="Automation Engineer",
                    company="Example Co",
                )
            )

    monkeypatch.setattr(
        "src.llm_job_extraction._get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    extracted = extract_job_data_with_web_search_fallback(
        "https://example.com/jobs/automation-engineer",
        JobPageSnapshot(
            requested_url="https://example.com/jobs/automation-engineer",
            errors=["No static HTML content was available for inspection."],
        ),
    )

    assert extracted.company == "Example Co"
    assert parse_calls[0]["tools"][0]["type"] == "web_search"
    assert parse_calls[0]["tool_choice"] == {"type": "web_search"}


def test_apply_url_resolver_prefers_snapshot_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_calls = []

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(
                output_parsed=ApplyUrlResolution(
                    status="resolved",
                    apply_url="https://example.com/jobs/automation-engineer/apply",
                    evidence=["Apply now"],
                    confidence="high",
                )
            )

    monkeypatch.setattr(
        "src.llm_job_extraction._get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    resolution = resolve_apply_url_from_snapshot(
        "https://example.com/jobs/automation-engineer",
        make_job_snapshot(),
        ExtractedJobData(title="Automation Engineer", company="Example Co"),
    )

    assert resolution.status == "resolved"
    assert resolution.apply_url == "https://example.com/jobs/automation-engineer/apply"
    assert "tools" not in parse_calls[0]


def test_job_page_snapshot_is_saved_separately_from_normalized_job(tmp_path: Path) -> None:
    saved_path = save_job_page_snapshot(tmp_path, "job-123", make_job_snapshot())
    reloaded = load_model(saved_path, JobPageSnapshot)

    assert saved_path.name == "job_page_snapshot.json"
    assert saved_path.parent.name == "job-123"
    assert not (saved_path.parent / "normalized_job.json").exists()
    assert reloaded.page_title == "Automation Engineer"
