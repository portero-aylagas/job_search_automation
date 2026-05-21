"""Persistence helpers for generated application packages."""

from __future__ import annotations

from pathlib import Path

from src.application_package_markdown import render_application_package_markdown
from src.paths import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME,
    application_package_markdown_path,
    application_package_paths,
    runtime_application_package_path,
    runtime_jobs_index_path,
    runtime_tracker_path,
)
from src.schemas import ApplicationPackage, JobListing, TrackerRecord
from src.storage import load_model, save_model

__all__ = [
    "APPLICATION_PACKAGE_MARKDOWN_FILENAME",
    "load_application_package",
    "save_application_package",
    "update_tracker_for_application_package",
]


def save_application_package(
    base_dir: Path | str,
    package: ApplicationPackage,
    job: JobListing,
) -> tuple[Path, Path]:
    """Persist package JSON and Markdown export for one job workspace."""

    json_path = runtime_application_package_path(base_dir, package.job_id)
    markdown_path = application_package_markdown_path(base_dir, package.job_id)
    save_model(json_path, package)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_application_package_markdown(package, job), encoding="utf-8")
    return json_path, markdown_path


def load_application_package(
    base_dir: Path | str,
    job_id: str,
) -> ApplicationPackage | None:
    """Load a package from runtime data or checked-in templates."""

    runtime_path, template_path = application_package_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationPackage, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationPackage, default=None)
    return None


def update_tracker_for_application_package(
    base_dir: Path | str,
    job_id: str,
    package_path: Path | str,
) -> list[TrackerRecord]:
    """Mark the tracker record as having an application draft package."""

    jobs_index_path = runtime_jobs_index_path(base_dir)
    tracker_path = runtime_tracker_path(base_dir)
    tracker_records = load_model(jobs_index_path, list[TrackerRecord], default=[])
    package_path_text = str(package_path)

    for record in tracker_records:
        if record.job_id != job_id:
            continue
        record.status = "application_draft"
        record.generated_package_path = package_path_text
        break

    save_model(jobs_index_path, tracker_records)
    save_model(tracker_path, tracker_records)
    return tracker_records
