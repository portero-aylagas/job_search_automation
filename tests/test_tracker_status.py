from pathlib import Path

import pytest

from src.schemas import TrackerRecord
from src.storage import load_model, save_model
from src.tracker_status import (
    TRACKER_STATUS_VALUES,
    load_tracker_records,
    tracker_status_options,
    update_manual_tracker_status,
    update_tracker_record,
)


def test_tracker_status_metadata_covers_every_status_once() -> None:
    options = tracker_status_options()

    assert [option["value"] for option in options] == list(TRACKER_STATUS_VALUES)
    assert len({option["value"] for option in options}) == len(TRACKER_STATUS_VALUES)
    assert all(option["label"] for option in options)
    assert all(option["badge"] for option in options)


def test_tracker_writes_only_canonical_jobs_index(tmp_path: Path) -> None:
    save_model(tmp_path / "data" / "runtime" / "jobs.json", [_tracker_record()])

    update_tracker_record(tmp_path, "job-1", status="ready_to_apply")

    records = load_model(tmp_path / "data" / "runtime" / "jobs.json", list[TrackerRecord])
    assert records[0].status == "ready_to_apply"
    assert not (tmp_path / "data" / "runtime" / "tracker.json").exists()


def test_tracker_loads_legacy_tracker_when_jobs_index_is_missing(tmp_path: Path) -> None:
    save_model(tmp_path / "data" / "runtime" / "tracker.json", [_tracker_record()])

    records = load_tracker_records(tmp_path)

    assert records[0].job_id == "job-1"


def test_manual_tracker_update_rejects_workflow_owned_status(tmp_path: Path) -> None:
    save_model(tmp_path / "data" / "runtime" / "jobs.json", [_tracker_record()])

    with pytest.raises(ValueError, match="cannot be set manually"):
        update_manual_tracker_status(tmp_path, "job-1", "ready_to_apply")


def test_manual_tracker_update_accepts_lifecycle_status(tmp_path: Path) -> None:
    save_model(tmp_path / "data" / "runtime" / "jobs.json", [_tracker_record()])

    records = update_manual_tracker_status(tmp_path, "job-1", "interview")

    assert records[0].status == "interview"


def _tracker_record() -> TrackerRecord:
    return TrackerRecord(
        job_id="job-1",
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/1",
        retrieval_mode="url",
        status="new",
    )

