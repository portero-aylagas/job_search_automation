from __future__ import annotations

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.job_intake import create_job_listing, persist_job_listing
from src.llm_job_extraction import ExtractedJobData, extract_job_data_from_url
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


def render_job_intake_page(base_dir: Path) -> None:
    st.title("Job Intake")
    st.write("Generate application data from a job URL.")

    success_message = st.session_state.pop("job_intake_success", None)
    if success_message:
        st.success(success_message)

    with st.form("job_url_form"):
        source_url = st.text_input("Job URL", placeholder="https://company.com/jobs/role")
        extract_submitted = st.form_submit_button("Extract Application Data")

    if extract_submitted:
        try:
            with st.spinner("Extracting job data with AI..."):
                extracted = extract_job_data_from_url(source_url)
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
            return
        st.session_state["job_intake_source_url"] = source_url.strip()
        st.session_state["job_intake_extracted"] = extracted.model_dump(mode="json")
        st.rerun()

    extracted_payload = st.session_state.get("job_intake_extracted")
    if not extracted_payload:
        return

    extracted_data = ExtractedJobData.model_validate(extracted_payload)
    source_url = st.session_state.get("job_intake_source_url", "")
    st.subheader("Review Extracted Data")
    st.caption("Review what the AI found before adding it to the application workflow.")

    with st.form("job_review_form"):
        left, right = st.columns(2)
        with left:
            title = st.text_input("Title", value=extracted_data.title)
            company = st.text_input("Company", value=extracted_data.company)
            location = st.text_input("Location", value=extracted_data.location)
            remote_policy = st.text_input("Remote Policy", value=extracted_data.remote_policy)
        with right:
            apply_url = st.text_input("Apply URL", value=extracted_data.apply_url)
            salary = st.text_input("Salary", value=extracted_data.salary)
            posted_date = st.text_input("Posted Date", value=extracted_data.posted_date)
            source_job_id = st.text_input("Source Job ID", value=extracted_data.source_job_id)

        description = st.text_area("Role Summary", value=extracted_data.description, height=180)
        requirements = st.text_area(
            "Requirements",
            value="\n".join(extracted_data.requirements),
            height=140,
        )
        responsibilities = st.text_area(
            "Responsibilities",
            value="\n".join(extracted_data.responsibilities),
            height=140,
        )
        nice_to_have_skills = st.text_area(
            "Nice-to-have Skills",
            value="\n".join(extracted_data.nice_to_have_skills),
            height=100,
        )
        st.markdown("**Additional Extracted Details**")
        dynamic_fields = []
        if extracted_data.dynamic_fields:
            for index, field in enumerate(extracted_data.dynamic_fields):
                name = field.name or f"Additional Detail {index + 1}"
                value = st.text_input(
                    name,
                    value=field.value,
                    key=f"dynamic_value_{index}",
                )
                dynamic_fields.append(
                    {
                        "dynamic": True,
                        "name": name,
                        "value": value,
                        "category": field.category,
                        "source_text": field.source_text,
                        "confidence": field.confidence,
                    }
                )
        else:
            st.caption("No additional details were extracted.")

        if extracted_data.missing_or_uncertain:
            st.warning("Needs review: " + "; ".join(extracted_data.missing_or_uncertain))

        save_submitted = st.form_submit_button("Add To Application Workflow")
        clear_submitted = st.form_submit_button("Start Over")

    if clear_submitted:
        st.session_state.pop("job_intake_source_url", None)
        st.session_state.pop("job_intake_extracted", None)
        st.rerun()

    if not save_submitted:
        return

    try:
        dynamic_fields = [field for field in dynamic_fields if field["name"] or field["value"]]
        validate_apply_url(apply_url)
        job_listing = create_job_listing(
            title=title,
            company=company,
            source_url=source_url,
            location=location,
            remote_policy=remote_policy,
            apply_url=apply_url,
            description=description,
            requirements=lines_from_text(requirements),
            responsibilities=lines_from_text(responsibilities),
            nice_to_have_skills=lines_from_text(nice_to_have_skills),
            salary=salary,
            posted_date=posted_date,
            source_job_id=source_job_id,
            job_details={
                "extraction_confidence": extracted_data.confidence,
                "dynamic_fields": dynamic_fields,
            },
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    except ValidationError as exc:
        st.error("The job could not be saved. Check the required fields and any URLs.")
        for error in exc.errors():
            location_path = " -> ".join(str(part) for part in error["loc"])
            st.write(f"- {location_path}: {error['msg']}")
        return

    persist_job_listing(base_dir, job_listing)
    st.session_state.pop("job_intake_source_url", None)
    st.session_state.pop("job_intake_extracted", None)
    st.session_state["job_intake_success"] = (
        f"Added {job_listing.company} / {job_listing.title} to the workflow."
    )
    st.rerun()


def lines_from_text(value: str) -> list[str]:
    return [line.strip("-• \t") for line in value.splitlines() if line.strip("-• \t")]


def validate_apply_url(value: str) -> None:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Apply URL is required before the workflow can continue.")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("Apply URL must be a working http or https URL, not an email or note.")


def main() -> None:
    st.set_page_config(page_title="Job Search Automation", layout="wide")
    profile, experience_units, tracker_records = load_app_data()

    st.sidebar.title("Job Search Automation")
    page = st.sidebar.radio("Navigate", ["Candidate Profile", "Job Intake", "Tracker"])

    if page == "Candidate Profile":
        render_candidate_profile_page(profile, experience_units)
    elif page == "Job Intake":
        render_job_intake_page(BASE_DIR)
    else:
        render_tracker_page(tracker_records)


if __name__ == "__main__":
    main()
