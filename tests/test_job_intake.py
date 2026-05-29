from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.job_intake_ui as job_intake_ui
from src.job_intake import (
    choose_valid_apply_url,
    create_job_listing,
    persist_job_listing,
    validate_apply_url,
)
from src.llm_job_extraction import ExtractedJobData
from src.schemas import JobListing, TrackerRecord
from src.storage import load_model


class FakeStreamlitContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def test_job_review_form_has_single_primary_save_action(monkeypatch) -> None:
    submitted_buttons: list[dict[str, object]] = []

    def fake_form_submit_button(label: str, **kwargs: object) -> bool:
        submitted_buttons.append({"label": label, **kwargs})
        return False

    fake_streamlit = SimpleNamespace(
        form=lambda _key: FakeStreamlitContext(),
        columns=lambda _count: [FakeStreamlitContext(), FakeStreamlitContext()],
        text_input=lambda _label, value="", **_kwargs: value,
        text_area=lambda _label, value="", **_kwargs: value,
        markdown=lambda _value: None,
        caption=lambda _value: None,
        warning=lambda _value: None,
        error=lambda _value: None,
        info=lambda _value: None,
        form_submit_button=fake_form_submit_button,
    )
    monkeypatch.setattr(job_intake_ui, "st", fake_streamlit)

    job_intake_ui.render_job_review_form(
        ExtractedJobData(
            title="Automation Engineer",
            company="Example Co",
            description="Build automation workflows.",
        ),
        "https://example.com/jobs/automation-engineer",
        "https://example.com/apply/automation-engineer",
    )

    assert submitted_buttons == [
        {"label": "Add To Application Workflow", "type": "primary"}
    ]


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


@pytest.mark.parametrize(
    "apply_url",
    [
        "mailto:jobs@example.com",
        "jobs@example.com",
        "tel:+49123456789",
        "ftp://example.com/apply",
    ],
)
def test_validate_apply_url_rejects_non_http_application_targets(apply_url: str) -> None:
    with pytest.raises(
        ValueError,
        match="Apply URL must be a working http or https URL",
    ):
        validate_apply_url(apply_url, "https://example.com/jobs/automation-engineer")


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
