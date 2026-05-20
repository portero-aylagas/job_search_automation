from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from src.paths import (
    runtime_jobs_index_path,
    runtime_normalized_job_path,
    runtime_tracker_path,
)
from src.schemas import JobListing, TrackerRecord
from src.storage import load_model, save_model


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


def _normalize_url_for_comparison(value: str) -> tuple[str, str, str]:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return parsed.scheme.lower(), parsed.netloc.lower(), path


def validate_apply_url(apply_url: str, source_url: str) -> None:
    normalized_apply_url = apply_url.strip()
    if not normalized_apply_url:
        raise ValueError("Apply URL is required before the workflow can continue.")
    normalized_source_url = require_text(source_url, "Job URL")
    if not normalized_apply_url.startswith(("http://", "https://")):
        raise ValueError("Apply URL must be a working http or https URL, not an email or note.")
    if _normalize_url_for_comparison(normalized_apply_url) == _normalize_url_for_comparison(
        normalized_source_url
    ):
        raise ValueError(
            "Apply URL must point to the application destination, not the job offer page."
        )


def choose_valid_apply_url(source_url: str, *candidates: str) -> str:
    for candidate in candidates:
        normalized_candidate = candidate.strip()
        if not normalized_candidate:
            continue
        try:
            validate_apply_url(normalized_candidate, source_url)
        except ValueError:
            continue
        return normalized_candidate
    return ""


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
    target = runtime_normalized_job_path(base_dir, job_listing.id)
    save_model(target, job_listing)
    return target


def upsert_tracker_record(base_dir: Path | str, job_listing: JobListing) -> list[TrackerRecord]:
    jobs_index_path = runtime_jobs_index_path(base_dir)
    tracker_path = runtime_tracker_path(base_dir)
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
