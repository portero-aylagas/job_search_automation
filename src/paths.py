from __future__ import annotations

from pathlib import Path

DATA_DIR = Path("data")
TEMPLATE_JOBS_DIR = DATA_DIR / "jobs"
RUNTIME_DATA_DIR = DATA_DIR / "runtime"
RUNTIME_JOBS_DIR = RUNTIME_DATA_DIR / "jobs"
OUTPUTS_DIR = Path("outputs")

CANDIDATE_PROFILE_FILENAME = "candidate_profile.json"
EXPERIENCE_UNITS_FILENAME = "experience_units.json"
JOBS_INDEX_FILENAME = "jobs.json"
TRACKER_FILENAME = "tracker.json"
LEGACY_PROFILE_FILENAME = "profile.json"
NORMALIZED_JOB_FILENAME = "normalized_job.json"
APPLICATION_REQUIREMENTS_FILENAME = "application_requirements.json"
APPLICATION_PAGE_SNAPSHOT_FILENAME = "application_page_snapshot.json"
APPLICATION_PACKAGE_FILENAME = "application_package.json"
APPLICATION_PACKAGE_MARKDOWN_FILENAME = "application_package.md"

CV_UPLOAD_DIR = RUNTIME_DATA_DIR / "candidate_profile" / "cv"
OPTIONAL_DOCUMENT_UPLOAD_DIR = RUNTIME_DATA_DIR / "candidate_profile" / "optional_documents"


def candidate_profile_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / DATA_DIR / CANDIDATE_PROFILE_FILENAME


def runtime_candidate_profile_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / RUNTIME_DATA_DIR / CANDIDATE_PROFILE_FILENAME


def legacy_profile_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / DATA_DIR / LEGACY_PROFILE_FILENAME


def experience_units_paths(base_dir: Path | str) -> tuple[Path, Path]:
    root = Path(base_dir)
    return (
        root / RUNTIME_DATA_DIR / EXPERIENCE_UNITS_FILENAME,
        root / DATA_DIR / EXPERIENCE_UNITS_FILENAME,
    )


def jobs_index_paths(base_dir: Path | str) -> tuple[Path, Path, Path, Path]:
    root = Path(base_dir)
    return (
        root / RUNTIME_DATA_DIR / JOBS_INDEX_FILENAME,
        root / RUNTIME_DATA_DIR / TRACKER_FILENAME,
        root / DATA_DIR / JOBS_INDEX_FILENAME,
        root / DATA_DIR / TRACKER_FILENAME,
    )


def runtime_job_dir(base_dir: Path | str, job_id: str) -> Path:
    return Path(base_dir) / RUNTIME_JOBS_DIR / job_id


def template_job_dir(base_dir: Path | str, job_id: str) -> Path:
    return Path(base_dir) / TEMPLATE_JOBS_DIR / job_id


def normalized_job_paths(base_dir: Path | str, job_id: str) -> tuple[Path, Path]:
    return (
        runtime_job_dir(base_dir, job_id) / NORMALIZED_JOB_FILENAME,
        template_job_dir(base_dir, job_id) / NORMALIZED_JOB_FILENAME,
    )


def runtime_normalized_job_path(base_dir: Path | str, job_id: str) -> Path:
    return runtime_job_dir(base_dir, job_id) / NORMALIZED_JOB_FILENAME


def application_requirements_paths(base_dir: Path | str, job_id: str) -> tuple[Path, Path]:
    return (
        runtime_job_dir(base_dir, job_id) / APPLICATION_REQUIREMENTS_FILENAME,
        template_job_dir(base_dir, job_id) / APPLICATION_REQUIREMENTS_FILENAME,
    )


def runtime_application_requirements_path(base_dir: Path | str, job_id: str) -> Path:
    return runtime_job_dir(base_dir, job_id) / APPLICATION_REQUIREMENTS_FILENAME


def runtime_application_page_snapshot_path(base_dir: Path | str, job_id: str) -> Path:
    return runtime_job_dir(base_dir, job_id) / APPLICATION_PAGE_SNAPSHOT_FILENAME


def application_package_paths(base_dir: Path | str, job_id: str) -> tuple[Path, Path]:
    return (
        runtime_job_dir(base_dir, job_id) / APPLICATION_PACKAGE_FILENAME,
        template_job_dir(base_dir, job_id) / APPLICATION_PACKAGE_FILENAME,
    )


def runtime_application_package_path(base_dir: Path | str, job_id: str) -> Path:
    return runtime_job_dir(base_dir, job_id) / APPLICATION_PACKAGE_FILENAME


def application_package_markdown_path(base_dir: Path | str, job_id: str) -> Path:
    return Path(base_dir) / OUTPUTS_DIR / job_id / APPLICATION_PACKAGE_MARKDOWN_FILENAME


def runtime_jobs_index_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / RUNTIME_DATA_DIR / JOBS_INDEX_FILENAME


def runtime_tracker_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / RUNTIME_DATA_DIR / TRACKER_FILENAME


def cv_upload_path(base_dir: Path | str, filename: str) -> Path:
    return Path(base_dir) / CV_UPLOAD_DIR / filename


def optional_document_upload_path(base_dir: Path | str, filename: str) -> Path:
    return Path(base_dir) / OPTIONAL_DOCUMENT_UPLOAD_DIR / filename
