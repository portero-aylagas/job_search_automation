from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import JobListing, TrackerRecord
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
