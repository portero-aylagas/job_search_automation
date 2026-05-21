"""Streamlit UI for the controlled job application workflow."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import candidate_profile_ui
from src.app_workflow import (
    apply_resolution_details,
    apply_url_review_messages,
    get_application_package_blockers,
    load_app_data,
    load_candidate_profile,
    mark_requirements_reviewed,
    resolved_apply_url,
    save_candidate_profile,
    validate_reviewed_apply_url,
)
from src.candidate_profile import (
    merge_supplemental_extracted_data,
    validate_candidate_profile,
)
from src.candidate_profile_ui import (
    CAREER_LEVEL_HELP,
    CAREER_LEVEL_OPTIONS,
    EMPLOYMENT_TYPE_OPTIONS,
    OPTIONAL_DOCUMENT_FILE_TYPES,
    OPTIONAL_DOCUMENT_TYPES,
    OPTIONAL_DOCUMENT_UPLOAD_MENUS,
    REMOTE_PREFERENCE_OPTIONS,
    WORK_AUTHORIZATION_OPTIONS,
    format_cv_parse_error,
    render_candidate_profile_page,
    required_label,
    work_authorization_index,
)
from src.job_intake_ui import (
    JobReviewFormState,
    build_reviewed_job_listing,
    render_job_intake_page,
)
from src.job_workspace_ui import render_jobs_page
from src.schemas import CandidateProfile, TrackerRecord
from src.ui_components import build_ai_usage_summary, format_detail_value

__all__ = [
    "CAREER_LEVEL_HELP",
    "CAREER_LEVEL_OPTIONS",
    "EMPLOYMENT_TYPE_OPTIONS",
    "JobReviewFormState",
    "OPTIONAL_DOCUMENT_FILE_TYPES",
    "OPTIONAL_DOCUMENT_TYPES",
    "OPTIONAL_DOCUMENT_UPLOAD_MENUS",
    "REMOTE_PREFERENCE_OPTIONS",
    "WORK_AUTHORIZATION_OPTIONS",
    "apply_resolution_details",
    "apply_url_review_messages",
    "build_ai_usage_summary",
    "build_reviewed_job_listing",
    "format_detail_value",
    "format_cv_parse_error",
    "get_candidate_profile_draft",
    "get_application_package_blockers",
    "get_latest_candidate_profile",
    "load_candidate_profile",
    "mark_requirements_reviewed",
    "merge_supplemental_extracted_data",
    "render_candidate_profile_page",
    "render_jobs_page",
    "required_label",
    "resolved_apply_url",
    "save_candidate_profile",
    "set_candidate_profile_draft",
    "validate_candidate_profile",
    "validate_reviewed_apply_url",
    "work_authorization_index",
]

BASE_DIR = Path(__file__).resolve().parent


def get_candidate_profile_draft(base_dir: Path) -> dict:
    """Load or initialize the candidate profile draft in Streamlit session state."""

    return candidate_profile_ui.get_candidate_profile_draft(base_dir)


def set_candidate_profile_draft(draft: dict) -> None:
    """Replace the candidate profile draft stored in Streamlit session state."""

    candidate_profile_ui.set_candidate_profile_draft(draft)


def get_latest_candidate_profile(base_dir: Path) -> CandidateProfile:
    """Return the current candidate profile draft as a validated model."""

    return CandidateProfile.model_validate(get_candidate_profile_draft(base_dir))


def render_tracker_page(tracker_records: list[TrackerRecord]) -> None:
    """Render the tracker table."""

    st.title("Tracker")
    sorted_records = sorted(
        tracker_records,
        key=lambda record: (record.status, record.company.lower(), record.title.lower()),
    )
    st.dataframe(
        [record.model_dump(mode="json") for record in sorted_records],
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    """Run the Streamlit application."""

    st.set_page_config(page_title="Job Search Automation", layout="wide")
    _, tracker_records = load_app_data(BASE_DIR)

    st.sidebar.title("Job Search Automation")
    page = st.sidebar.radio("Navigate", ["Candidate Profile", "Job Intake", "Jobs", "Tracker"])

    if page == "Candidate Profile":
        render_candidate_profile_page(BASE_DIR)
    elif page == "Job Intake":
        render_job_intake_page(BASE_DIR)
    elif page == "Jobs":
        render_jobs_page(BASE_DIR, tracker_records)
    else:
        render_tracker_page(tracker_records)


if __name__ == "__main__":
    main()
