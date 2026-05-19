from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from src.schemas import JobListing, TrackerRecord
from src.storage import load_model, save_model

JOBS_INDEX_FILENAME = "jobs.json"
RUNTIME_DATA_DIR = Path("data/runtime")


def require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "job"


def build_job_id(title: str, company: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")
    return f"job-{timestamp}-{slugify(company)}-{slugify(title)}"


def create_job_listing(
    *,
    title: str,
    company: str,
    source_url: str,
    location: str = "",
    remote_policy: str = "",
    apply_url: str = "",
    description: str = "",
    requirements: list[str] | None = None,
    responsibilities: list[str] | None = None,
    nice_to_have_skills: list[str] | None = None,
    salary: str = "",
    posted_date: str = "",
    source_job_id: str = "",
    job_details: dict[str, object] | None = None,
    now: datetime | None = None,
) -> JobListing:
    normalized_title = require_text(title, "Title")
    normalized_company = require_text(company, "Company")
    normalized_source_url = require_text(source_url, "Job URL")
    normalized_apply_url = apply_url.strip() or None
    normalized_location = location.strip() or None
    normalized_remote_policy = remote_policy.strip() or None
    normalized_description = description.strip() or None

    return JobListing(
        id=build_job_id(title=normalized_title, company=normalized_company, now=now),
        title=normalized_title,
        company=normalized_company,
        source_url=normalized_source_url,
        retrieval_mode="url",
        source_job_id=source_job_id.strip() or None,
        location=normalized_location,
        remote_policy=normalized_remote_policy,
        apply_url=normalized_apply_url,
        description=normalized_description,
        requirements=requirements or [],
        responsibilities=responsibilities or [],
        nice_to_have_skills=nice_to_have_skills or [],
        salary=salary.strip() or None,
        posted_date=posted_date.strip() or None,
        job_details=job_details or {},
    )


def save_normalized_job(base_dir: Path | str, job_listing: JobListing) -> Path:
    target = (
        Path(base_dir)
        / RUNTIME_DATA_DIR
        / "jobs"
        / job_listing.id
        / "normalized_job.json"
    )
    save_model(target, job_listing)
    return target


def upsert_tracker_record(base_dir: Path | str, job_listing: JobListing) -> list[TrackerRecord]:
    root = Path(base_dir)
    jobs_index_path = root / RUNTIME_DATA_DIR / JOBS_INDEX_FILENAME
    tracker_path = root / RUNTIME_DATA_DIR / "tracker.json"
    tracker_records = load_model(jobs_index_path, list[TrackerRecord], default=[])

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

    save_model(jobs_index_path, tracker_records)
    save_model(tracker_path, tracker_records)
    return tracker_records


def persist_job_listing(base_dir: Path | str, job_listing: JobListing) -> Path:
    job_path = save_normalized_job(base_dir, job_listing)
    upsert_tracker_record(base_dir, job_listing)
    return job_path
