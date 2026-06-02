"""Canonical tracker status policy and persistence helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

from src.paths import jobs_index_paths, runtime_jobs_index_path
from src.storage import load_model, save_model

if TYPE_CHECKING:
    from src.schemas import JobListing, TrackerRecord

TrackerStatus: TypeAlias = Literal[
    "new",
    "analyzed",
    "interesting",
    "rejected_by_user",
    "application_draft",
    "ready_to_apply",
    "agent_assistance_attempted",
    "applied_manually",
    "applied_with_agent_assistance",
    "interview",
    "rejected",
    "offer",
    "closed",
]

TRACKER_STATUS_VALUES: tuple[TrackerStatus, ...] = (
    "new",
    "analyzed",
    "interesting",
    "rejected_by_user",
    "application_draft",
    "ready_to_apply",
    "agent_assistance_attempted",
    "applied_manually",
    "applied_with_agent_assistance",
    "interview",
    "rejected",
    "offer",
    "closed",
)

USER_EDITABLE_TRACKER_STATUSES: tuple[TrackerStatus, ...] = (
    "new",
    "interesting",
    "rejected_by_user",
    "applied_manually",
    "applied_with_agent_assistance",
    "interview",
    "rejected",
    "offer",
    "closed",
)

TRACKER_STATUS_LABELS: dict[TrackerStatus, str] = {
    "new": "New",
    "analyzed": "Analyzed",
    "interesting": "Interesting",
    "rejected_by_user": "Rejected by user",
    "application_draft": "Application Draft",
    "ready_to_apply": "Ready to Apply",
    "agent_assistance_attempted": "Agent Assistance Attempted",
    "applied_manually": "Applied Manually",
    "applied_with_agent_assistance": "Applied with Agent Assistance",
    "interview": "Interview",
    "rejected": "Rejected",
    "offer": "Offer",
    "closed": "Closed",
}

TRACKER_STATUS_BADGES: dict[TrackerStatus, str] = {
    "new": "missing",
    "analyzed": "needs-review",
    "interesting": "needs-review",
    "rejected_by_user": "blocked",
    "application_draft": "needs-review",
    "ready_to_apply": "ready",
    "agent_assistance_attempted": "needs-review",
    "applied_manually": "complete",
    "applied_with_agent_assistance": "complete",
    "interview": "complete",
    "rejected": "blocked",
    "offer": "complete",
    "closed": "blocked",
}

TRACKER_STATUS_FILTERS: tuple[dict[str, object], ...] = (
    {"label": "All", "statuses": list(TRACKER_STATUS_VALUES)},
    {"label": "New", "statuses": ["new"]},
    {"label": "In progress", "statuses": ["analyzed", "interesting"]},
    {"label": "Application Draft", "statuses": ["application_draft"]},
    {"label": "Ready", "statuses": ["ready_to_apply"]},
    {"label": "Agent Attempted", "statuses": ["agent_assistance_attempted"]},
    {"label": "Applied", "statuses": ["applied_manually", "applied_with_agent_assistance"]},
    {"label": "Interview / Offer", "statuses": ["interview", "offer"]},
    {"label": "Closed", "statuses": ["rejected_by_user", "rejected", "closed"]},
)


def normalize_tracker_status(value: str) -> TrackerStatus:
    """Return a validated tracker status value."""

    if value in TRACKER_STATUS_VALUES:
        return value  # type: ignore[return-value]
    raise ValueError(f"Unsupported tracker status: {value}")


def tracker_status_label(status: str) -> str:
    """Return the human-readable label for a tracker status."""

    return TRACKER_STATUS_LABELS.get(normalize_tracker_status(status), status)


def tracker_status_badge(status: str) -> str:
    """Return the UI badge category for a tracker status."""

    return TRACKER_STATUS_BADGES.get(normalize_tracker_status(status), "missing")


def tracker_status_options() -> list[dict[str, object]]:
    """Return status metadata for API clients."""

    return [
        {
            "value": status,
            "label": TRACKER_STATUS_LABELS[status],
            "badge": TRACKER_STATUS_BADGES[status],
            "user_editable": status in USER_EDITABLE_TRACKER_STATUSES,
        }
        for status in TRACKER_STATUS_VALUES
    ]


def tracker_status_filters() -> list[dict[str, object]]:
    """Return tracker quick-filter metadata for API clients."""

    return [
        {"label": str(item["label"]), "statuses": list(item["statuses"])}
        for item in TRACKER_STATUS_FILTERS
    ]


def load_tracker_records(base_dir: Path | str) -> list["TrackerRecord"]:
    """Load tracker records from the canonical index, with legacy fallback."""

    from src.schemas import TrackerRecord

    runtime_jobs_index, runtime_tracker, template_jobs_index, template_tracker = jobs_index_paths(
        base_dir
    )
    if runtime_jobs_index.exists():
        return load_model(runtime_jobs_index, list[TrackerRecord], default=[])
    if runtime_tracker.exists():
        return load_model(runtime_tracker, list[TrackerRecord], default=[])
    if template_jobs_index.exists():
        return load_model(template_jobs_index, list[TrackerRecord], default=[])
    if template_tracker.exists():
        return load_model(template_tracker, list[TrackerRecord], default=[])
    return []


def save_tracker_records(base_dir: Path | str, records: list["TrackerRecord"]) -> Path:
    """Persist tracker records to the canonical runtime jobs index."""

    target = runtime_jobs_index_path(base_dir)
    save_model(target, records)
    return target


def upsert_tracker_record(base_dir: Path | str, job_listing: "JobListing") -> list["TrackerRecord"]:
    """Create or replace the tracker entry for a saved job listing."""

    from src.schemas import TrackerRecord

    tracker_records = load_tracker_records(base_dir)
    new_record = TrackerRecord(
        job_id=job_listing.id,
        title=job_listing.title,
        company=job_listing.company,
        source_url=job_listing.source_url,
        location=job_listing.location,
        retrieval_mode=job_listing.retrieval_mode,
        status="new",
    )
    existing_index = next(
        (index for index, record in enumerate(tracker_records) if record.job_id == job_listing.id),
        None,
    )
    if existing_index is None:
        tracker_records.append(new_record)
    else:
        tracker_records[existing_index] = new_record
    save_tracker_records(base_dir, tracker_records)
    return tracker_records


def update_tracker_record(
    base_dir: Path | str,
    job_id: str,
    *,
    status: TrackerStatus | None = None,
    generated_package_path: Path | str | None = None,
    match_score: float | None = None,
) -> list["TrackerRecord"]:
    """Update one tracker record through the canonical persistence path."""

    tracker_records = load_tracker_records(base_dir)
    next_status = normalize_tracker_status(status) if status is not None else None
    package_path_text = str(generated_package_path) if generated_package_path is not None else None
    for record in tracker_records:
        if record.job_id != job_id:
            continue
        if next_status is not None:
            record.status = next_status
        if package_path_text is not None:
            record.generated_package_path = package_path_text
        if match_score is not None:
            record.match_score = match_score
        save_tracker_records(base_dir, tracker_records)
        return tracker_records
    raise ValueError(f"Tracker record not found for job {job_id}.")


def update_manual_tracker_status(
    base_dir: Path | str,
    job_id: str,
    status: str,
) -> list["TrackerRecord"]:
    """Update a tracker status selected manually by the user."""

    next_status = normalize_tracker_status(status)
    if next_status not in USER_EDITABLE_TRACKER_STATUSES:
        raise ValueError(f"Status {TRACKER_STATUS_LABELS[next_status]} cannot be set manually.")
    return update_tracker_record(base_dir, job_id, status=next_status)
