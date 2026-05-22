"""Persistence helpers for generated application packages."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from src.application_package_markdown import render_application_package_markdown
from src.paths import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME,
    application_package_artifacts_dir,
    application_package_markdown_path,
    application_package_paths,
    runtime_application_package_path,
    runtime_jobs_index_path,
    runtime_tracker_path,
)
from src.schemas import ApplicationArtifact, ApplicationPackage, JobListing, TrackerRecord
from src.storage import load_model, save_model

__all__ = [
    "APPLICATION_PACKAGE_MARKDOWN_FILENAME",
    "export_cover_letter_artifact",
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
    _save_uploadable_package_artifacts(base_dir, package)
    save_model(json_path, package)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_application_package_markdown(package, job), encoding="utf-8")
    return json_path, markdown_path


def _save_uploadable_package_artifacts(
    base_dir: Path | str,
    package: ApplicationPackage,
) -> None:
    """Write generated package artifacts that can be referenced by fill plans."""

    artifacts_dir = application_package_artifacts_dir(base_dir, package.job_id)
    for artifact in package.artifacts:
        if not _is_cover_letter_artifact(artifact) or not artifact.content.strip():
            continue
        _export_artifact_pdf(artifact, artifacts_dir, metadata_prefix="generated")


def export_cover_letter_artifact(
    package: ApplicationPackage,
    destination_dir: Path | str,
) -> Path | None:
    """Export the first cover-letter artifact to a user-selected folder."""

    for artifact in package.artifacts:
        if not _is_cover_letter_artifact(artifact) or not artifact.content.strip():
            continue
        return _export_artifact_pdf(
            artifact,
            Path(destination_dir),
            metadata_prefix="downloaded",
        )
    return None


def _export_artifact_pdf(
    artifact: ApplicationArtifact,
    destination_dir: Path,
    *,
    metadata_prefix: str,
) -> Path:
    """Write one generated artifact as a PDF and record its path in metadata."""

    destination_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = destination_dir / f"{_safe_artifact_filename(artifact.id)}.pdf"
    _write_text_pdf(artifact_path, artifact.label, artifact.content)
    metadata = dict(artifact.metadata)
    metadata[f"{metadata_prefix}_file_path"] = str(artifact_path)
    metadata[f"{metadata_prefix}_file_format"] = "pdf"
    metadata[f"{metadata_prefix}_file_mime_type"] = "application/pdf"
    artifact.metadata = metadata
    return artifact_path


def _is_cover_letter_artifact(artifact: ApplicationArtifact) -> bool:
    artifact_type = artifact.type.casefold()
    label = artifact.label.casefold()
    return artifact_type == "cover_letter" or "cover letter" in label


def _write_text_pdf(path: Path, title: str, content: str) -> None:
    """Write plain generated artifact text as a simple PDF document."""

    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 18)]
    for block in content.strip().split("\n\n"):
        normalized_block = "<br/>".join(escape(line) for line in block.splitlines())
        if normalized_block.strip():
            story.extend([Paragraph(normalized_block, styles["BodyText"]), Spacer(1, 10)])
    document = SimpleDocTemplate(str(path), pagesize=A4)
    document.build(story)


def _safe_artifact_filename(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip(".-_")
    return normalized or "artifact"


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
