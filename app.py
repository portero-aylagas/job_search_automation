from __future__ import annotations

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.job_intake import create_job_listing, persist_job_listing
from src.llm_job_extraction import ExtractedJobData, extract_job_data_from_url
from src.sample_data import bootstrap_sample_data
from src.schemas import CandidateProfile, ExperienceUnit, JobListing, TrackerRecord
from src.storage import load_model

BASE_DIR = Path(__file__).resolve().parent


def load_app_data() -> tuple[CandidateProfile, list[ExperienceUnit], list[TrackerRecord]]:
    bootstrap_sample_data(BASE_DIR)

    profile = load_model(BASE_DIR / "data/profile.json", CandidateProfile)
    experience_units = load_model(
        BASE_DIR / "data/experience_units.json",
        list[ExperienceUnit],
    )
    tracker_records = load_jobs_index(BASE_DIR)
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


def render_jobs_page(base_dir: Path, tracker_records: list[TrackerRecord]) -> None:
    st.title("Jobs")
    if not tracker_records:
        st.info("No jobs have been added yet.")
        return

    sorted_records = sorted(
        tracker_records,
        key=lambda record: (record.company.lower(), record.title.lower(), record.job_id),
    )
    selected_record = st.selectbox(
        "Job",
        sorted_records,
        format_func=job_option_label,
    )
    job_listing = load_normalized_job(base_dir, selected_record.job_id)

    st.header(f"{selected_record.title}")
    st.caption(selected_record.company)

    status_left, status_right, status_third = st.columns(3)
    status_left.metric("Status", selected_record.status)
    if selected_record.match_score is None:
        match_score = "Not analyzed"
    else:
        match_score = f"{selected_record.match_score:g}"
    status_right.metric("Match Score", match_score)
    status_third.metric("Retrieval", selected_record.retrieval_mode)

    st.divider()
    if job_listing is None:
        render_tracker_job_summary(selected_record)
        st.warning("Full intake data is not available for this job yet.")
        return

    render_job_intake_summary(job_listing)


def load_normalized_job(base_dir: Path, job_id: str) -> JobListing | None:
    path = base_dir / "data" / "jobs" / job_id / "normalized_job.json"
    return load_model(path, JobListing, default=None)


def load_jobs_index(base_dir: Path) -> list[TrackerRecord]:
    jobs_index_path = base_dir / "data" / "jobs.json"
    tracker_path = base_dir / "data" / "tracker.json"
    return load_model(jobs_index_path, list[TrackerRecord], default=None) or load_model(
        tracker_path,
        list[TrackerRecord],
        default=[],
    )


def job_option_label(record: TrackerRecord) -> str:
    return f"{record.company} / {record.title}"


def render_tracker_job_summary(record: TrackerRecord) -> None:
    st.subheader("Job Summary")
    summary = {
        "Company": record.company,
        "Title": record.title,
        "Location": record.location or "Not specified",
        "Source URL": str(record.source_url),
        "Notes": record.notes or "None",
    }
    for label, value in summary.items():
        st.markdown(f"**{label}**")
        st.write(value)


def render_job_intake_summary(job: JobListing) -> None:
    st.subheader("Intake Data")
    left, right = st.columns(2)
    with left:
        render_field("Company", job.company)
        render_field("Location", job.location)
        render_field("Remote Policy", job.remote_policy)
        render_field("Salary", job.salary)
    with right:
        render_field("Source URL", str(job.source_url))
        render_field("Apply URL", str(job.apply_url) if job.apply_url else None)
        render_field("Posted Date", job.posted_date)
        render_field("Source Job ID", job.source_job_id)

    if job.description:
        st.markdown("**Role Summary**")
        st.write(job.description)

    render_list("Requirements", job.requirements)
    render_list("Responsibilities", job.responsibilities)
    render_list("Nice-to-have Skills", job.nice_to_have_skills)
    render_additional_details(job.job_details)


def render_field(label: str, value: str | None) -> None:
    st.markdown(f"**{label}**")
    st.write(value or "Not specified")


def render_list(label: str, values: list[str]) -> None:
    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values:
        st.write(f"- {value}")


def render_additional_details(job_details: dict[str, object]) -> None:
    dynamic_fields = job_details.get("dynamic_fields")
    rendered_any = False

    if isinstance(dynamic_fields, list):
        st.markdown("**Additional Extracted Details**")
        for field in dynamic_fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "Additional Detail")
            value = field.get("value")
            render_field(name, str(value) if value is not None else None)
            rendered_any = True

    remaining_details = {
        key: value
        for key, value in job_details.items()
        if key not in {"dynamic_fields", "extraction_confidence"} and value
    }
    if remaining_details:
        if not rendered_any:
            st.markdown("**Additional Extracted Details**")
        for key, value in remaining_details.items():
            render_field(key.replace("_", " ").title(), format_detail_value(value))


def format_detail_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


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
    page = st.sidebar.radio("Navigate", ["Candidate Profile", "Job Intake", "Jobs", "Tracker"])

    if page == "Candidate Profile":
        render_candidate_profile_page(profile, experience_units)
    elif page == "Job Intake":
        render_job_intake_page(BASE_DIR)
    elif page == "Jobs":
        render_jobs_page(BASE_DIR, tracker_records)
    else:
        render_tracker_page(tracker_records)


if __name__ == "__main__":
    main()
