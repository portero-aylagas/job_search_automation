"""Streamlit UI for the controlled job application workflow."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import candidate_profile_ui
from src.agent_ui import (
    SELECTED_JOB_STATE_KEY,
    SELECTED_PAGE_STATE_KEY,
    render_agent_page,
    render_karen_chat_window,
)
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
    validate_candidate_discovery_preferences,
    validate_candidate_profile,
    validate_known_job_candidate_profile,
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
    "render_agent_page",
    "render_karen_chat_window",
    "render_jobs_page",
    "required_label",
    "resolved_apply_url",
    "save_candidate_profile",
    "set_candidate_profile_draft",
    "validate_candidate_discovery_preferences",
    "validate_candidate_profile",
    "validate_known_job_candidate_profile",
    "validate_reviewed_apply_url",
    "work_authorization_index",
]

BASE_DIR = Path(__file__).resolve().parent
PAGE_NAMES = ["Candidate Profile", "Job Intake", "Jobs", "Tracker", "Agent"]


def inject_app_shell_styles() -> None:
    """Apply viewport layout styles for the main page and Karen chat."""

    if not hasattr(st, "markdown"):
        return

    st.markdown(
        """
<style>
div[data-testid="stVerticalBlock"]:has(.karen-app-shell-anchor)
  > div[data-testid="stHorizontalBlock"] {
    align-items: stretch;
}

div[data-testid="stVerticalBlock"]:has(.karen-app-shell-anchor)
  > div[data-testid="stHorizontalBlock"]
  > div:nth-of-type(1)
  > div[data-testid="stVerticalBlock"] {
    max-height: calc(100vh - 7rem);
    overflow-y: auto;
    padding-right: 0.75rem;
}

div[data-testid="stVerticalBlock"]:has(.karen-app-shell-anchor)
  > div[data-testid="stHorizontalBlock"]
  > div:nth-of-type(2)
  > div[data-testid="stVerticalBlock"] {
    position: sticky;
    top: 4.75rem;
    max-height: calc(100vh - 6rem);
    overflow-y: auto;
    padding-bottom: 1rem;
}

div[data-testid="stVerticalBlock"]:has(.karen-chat-input-anchor)
  div[data-testid="stChatInput"] {
    position: sticky;
    bottom: 0;
    z-index: 20;
    background: var(--background-color);
    border-top: 1px solid rgba(49, 51, 63, 0.18);
    padding-top: 0.5rem;
}
</style>
<span class="karen-app-shell-anchor"></span>
""",
        unsafe_allow_html=True,
    )


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
    if SELECTED_PAGE_STATE_KEY not in st.session_state:
        st.session_state[SELECTED_PAGE_STATE_KEY] = "Candidate Profile"
    selected_page = st.session_state.get(SELECTED_PAGE_STATE_KEY, "Candidate Profile")
    if selected_page not in PAGE_NAMES:
        selected_page = "Candidate Profile"
        st.session_state[SELECTED_PAGE_STATE_KEY] = selected_page
    selected_index = PAGE_NAMES.index(selected_page)
    page = st.sidebar.radio(
        "Navigate",
        PAGE_NAMES,
        index=selected_index,
        key=SELECTED_PAGE_STATE_KEY,
    )

    render_page_with_karen(BASE_DIR, page, tracker_records)


def render_page_with_karen(
    base_dir: Path,
    page: str,
    tracker_records: list[TrackerRecord],
) -> None:
    """Render one main app page with Karen in the persistent right column."""

    inject_app_shell_styles()
    main_column, karen_column = st.columns([0.68, 0.32], gap="large")

    with main_column:
        if page == "Candidate Profile":
            render_candidate_profile_page(base_dir)
        elif page == "Job Intake":
            render_job_intake_page(base_dir)
        elif page == "Agent":
            render_agent_page(base_dir, tracker_records)
        elif page == "Jobs":
            render_jobs_page(base_dir, tracker_records)
        else:
            render_tracker_page(tracker_records)

    with karen_column:
        selected_job_id = st.session_state.get(SELECTED_JOB_STATE_KEY)
        render_karen_chat_window(
            base_dir,
            current_page=page,
            selected_job_id=selected_job_id,
        )


if __name__ == "__main__":
    main()
