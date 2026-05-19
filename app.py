from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.sample_data import bootstrap_sample_data
from src.schemas import CandidateProfile, ExperienceUnit, TrackerRecord
from src.storage import load_model

BASE_DIR = Path(__file__).resolve().parent


def load_app_data() -> tuple[CandidateProfile, list[ExperienceUnit], list[TrackerRecord]]:
    bootstrap_sample_data(BASE_DIR)

    profile = load_model(BASE_DIR / "data/profile.json", CandidateProfile)
    experience_units = load_model(
        BASE_DIR / "data/experience_units.json",
        list[ExperienceUnit],
    )
    tracker_records = load_model(
        BASE_DIR / "data/tracker.json",
        list[TrackerRecord],
    )
    return profile, experience_units, tracker_records


def render_candidate_profile_page(
    profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
) -> None:
    st.title("Candidate Profile")
    st.subheader(profile.full_name)
    st.write(profile.professional_summary)

    left, right = st.columns(2)
    with left:
        st.markdown("**Target Roles**")
        st.write(profile.target_roles)
        st.markdown("**Skills**")
        st.write(profile.skills)
        st.markdown("**Languages**")
        st.write(profile.languages)
    with right:
        st.markdown("**Target Locations**")
        st.write(profile.target_locations)
        st.markdown("**Salary Expectation**")
        st.write(profile.salary_expectation or "Not specified")
        st.markdown("**Constraints**")
        st.write(profile.constraints or ["None listed"])

    st.markdown("**Documents Used**")
    st.write(profile.documents_used or ["None listed"])

    st.divider()
    st.subheader("Experience Units")
    for unit in experience_units:
        with st.expander(f"{unit.title} · {unit.organization}", expanded=False):
            st.caption(unit.date_range)
            st.write(unit.summary)
            st.markdown("**Skills**")
            st.write(unit.skills)
            st.markdown("**Evidence Points**")
            for point in unit.evidence_points:
                st.write(f"- {point}")


def render_tracker_page(tracker_records: list[TrackerRecord]) -> None:
    st.title("Tracker")
    sorted_records = sorted(
        tracker_records,
        key=lambda record: (record.status, record.company.lower(), record.title.lower()),
    )
    st.dataframe(
        [record.model_dump(mode="json") for record in sorted_records],
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Job Search Automation", layout="wide")
    profile, experience_units, tracker_records = load_app_data()

    st.sidebar.title("Job Search Automation")
    page = st.sidebar.radio("Navigate", ["Candidate Profile", "Tracker"])

    if page == "Candidate Profile":
        render_candidate_profile_page(profile, experience_units)
    else:
        render_tracker_page(tracker_records)


if __name__ == "__main__":
    main()
