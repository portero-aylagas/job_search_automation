"""Persistence helpers for generated application packages."""

from __future__ import annotations

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
)
from src.schemas import ApplicationArtifact, ApplicationPackage, JobListing, TrackerRecord
from src.storage import load_model, save_model
from src.tracker_status import update_tracker_record

__all__ = [
    "APPLICATION_PACKAGE_MARKDOWN_FILENAME",
    "export_cover_letter_artifact",
    "load_application_package",
    "save_application_package",
    "update_tracker_for_application_package",
]

COVER_LETTER_ARTIFACT_FILENAME = "cover_letter.pdf"


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
        _export_artifact_pdf(
            artifact,
            artifacts_dir,
            metadata_prefix="generated",
            overwrite=True,
        )


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
            overwrite=False,
        )
    return None


def _export_artifact_pdf(
    artifact: ApplicationArtifact,
    destination_dir: Path,
    *,
    metadata_prefix: str,
    overwrite: bool,
) -> Path:
    """Write one generated artifact as a PDF and record its path in metadata."""

    destination_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = destination_dir / COVER_LETTER_ARTIFACT_FILENAME
    if not overwrite:
        artifact_path = _available_artifact_path(artifact_path)
    _write_text_pdf(artifact_path, _cover_letter_pdf_content(artifact))
    metadata = dict(artifact.metadata)
    metadata[f"{metadata_prefix}_file_path"] = str(artifact_path)
    metadata[f"{metadata_prefix}_file_format"] = "pdf"
    metadata[f"{metadata_prefix}_file_mime_type"] = "application/pdf"
    artifact.metadata = metadata
    return artifact_path


def _available_artifact_path(path: Path) -> Path:
    """Return a non-existing artifact path by adding a numeric suffix if needed."""

    if not path.exists():
        return path

    for suffix in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"No available filename found for {path}.")


def _is_cover_letter_artifact(artifact: ApplicationArtifact) -> bool:
    artifact_type = artifact.type.casefold()
    label = artifact.label.casefold()
    return artifact_type == "cover_letter" or "cover letter" in label


def _cover_letter_pdf_content(artifact: ApplicationArtifact) -> str:
    """Return cover letter text without internal artifact headings."""

    lines = artifact.content.strip().splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if heading_index is None:
        return ""

    heading = lines[heading_index].strip().casefold()
    removable_headings = {
        artifact.label.strip().casefold(),
        "cover letter",
        "cover letter draft",
        "cover letter reviewed",
        "reviewed cover letter",
        COVER_LETTER_ARTIFACT_FILENAME.casefold(),
    }
    if heading in removable_headings:
        del lines[heading_index]
    return "\n".join(lines).strip()


def _write_text_pdf(path: Path, content: str) -> None:
    """Write plain generated artifact text as a simple PDF document."""

    styles = getSampleStyleSheet()
    story = []
    for block in content.strip().split("\n\n"):
        normalized_block = "<br/>".join(escape(line) for line in block.splitlines())
        if normalized_block.strip():
            story.extend([Paragraph(normalized_block, styles["BodyText"]), Spacer(1, 10)])
    document = SimpleDocTemplate(str(path), pagesize=A4)
    document.build(story)


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

    return update_tracker_record(
        base_dir,
        job_id,
        status="application_draft",
        generated_package_path=package_path,
    )
