from __future__ import annotations

from pathlib import Path

from src import app_workflow
from src.llm_job_extraction import ApplyUrlResolution


def test_app_workflow_has_no_streamlit_dependency() -> None:
    source = Path("src/app_workflow.py").read_text(encoding="utf-8")

    assert "streamlit" not in source


def test_load_app_data_uses_supplied_base_dir(tmp_path: Path) -> None:
    profile, tracker_records = app_workflow.load_app_data(tmp_path)

    assert profile.candidate_profile.profile_status == "draft"
    assert tracker_records
    assert (tmp_path / "data" / "candidate_profile.json").is_file()
    assert (tmp_path / "data" / "runtime" / "jobs.json").is_file()


def test_apply_resolution_details_marks_manual_unverified_url() -> None:
    details = app_workflow.apply_resolution_details(
        "https://example.com/apply/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        None,
    )

    assert details["status"] == "manual_review"
    assert details["verified_by_resolver"] is False
    assert details["manual_override"] is True


def test_resolved_apply_url_rejects_invalid_resolved_candidate() -> None:
    resolution = ApplyUrlResolution(
        status="resolved",
        apply_url="mailto:jobs@example.com",
    )

    assert app_workflow.resolved_apply_url(
        "https://example.com/jobs/automation-engineer",
        resolution,
    ) == ""
