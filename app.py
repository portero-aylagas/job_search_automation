from __future__ import annotations

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.application_requirements import (
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.job_intake import (
    choose_valid_apply_url,
    create_job_listing,
    persist_job_listing,
    validate_apply_url,
)
from src.llm_job_extraction import (
    ApplyUrlResolution,
    ExtractedJobData,
    extract_job_data_from_url,
    resolve_apply_url_from_url,
)
from src.sample_data import bootstrap_sample_data
from src.schemas import (
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    TrackerRecord,
)
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
        width="stretch",
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
    render_application_requirements_panel(base_dir, job_listing)


def load_normalized_job(base_dir: Path, job_id: str) -> JobListing | None:
    runtime_path = base_dir / "data" / "runtime" / "jobs" / job_id / "normalized_job.json"
    template_path = base_dir / "data" / "jobs" / job_id / "normalized_job.json"
    if runtime_path.exists():
        return load_model(runtime_path, JobListing, default=None)
    if template_path.exists():
        return load_model(template_path, JobListing, default=None)
    return None


def load_application_requirements(
    base_dir: Path,
    job_id: str,
) -> ApplicationRequirements | None:
    runtime_path = (
        base_dir
        / "data"
        / "runtime"
        / "jobs"
        / job_id
        / "application_requirements.json"
    )
    template_path = base_dir / "data" / "jobs" / job_id / "application_requirements.json"
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationRequirements, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationRequirements, default=None)
    return None


def load_jobs_index(base_dir: Path) -> list[TrackerRecord]:
    runtime_jobs_index = base_dir / "data" / "runtime" / "jobs.json"
    template_jobs_index = base_dir / "data" / "jobs.json"
    runtime_tracker = base_dir / "data" / "runtime" / "tracker.json"
    template_tracker = base_dir / "data" / "tracker.json"
    if runtime_jobs_index.exists():
        return load_model(runtime_jobs_index, list[TrackerRecord], default=[])
    if runtime_tracker.exists():
        return load_model(runtime_tracker, list[TrackerRecord], default=[])
    if template_jobs_index.exists():
        return load_model(template_jobs_index, list[TrackerRecord], default=[])
    if template_tracker.exists():
        return load_model(template_tracker, list[TrackerRecord], default=[])
    return []


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


def render_application_requirements_panel(base_dir: Path, job: JobListing) -> None:
    st.divider()
    st.subheader("Application Requirements")
    requirements = load_application_requirements(base_dir, job.id)

    if job.apply_url is None:
        st.warning("Apply URL is missing. Requirements discovery is blocked.")
        return

    if st.button("Discover Requirements From Apply URL"):
        try:
            with st.spinner("Inspecting apply page requirements..."):
                discovery_state = run_requirements_discovery_graph(job)
                requirements = discovery_state["requirements"]
                save_application_page_snapshot(base_dir, job.id, discovery_state["snapshot"])
                save_application_requirements(base_dir, requirements)
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
            return
        st.success("Application requirements were saved for review.")

    if requirements is None:
        st.info("No application requirements have been discovered yet.")
        return

    render_application_requirements(requirements)


def render_application_requirements(requirements: ApplicationRequirements) -> None:
    status_columns = st.columns(3)
    status_columns[0].metric("Status", requirements.status)
    status_columns[1].metric("Job Preserving", "Yes" if requirements.job_preserving else "No")
    status_columns[2].metric("Confidence", requirements.confidence)

    if requirements.blocked_reason:
        st.warning(requirements.blocked_reason)

    render_requirement_findings("Required Documents", requirements.required_documents)
    render_requirement_findings("Upload Expectations", requirements.upload_expectations)
    render_form_fields("Profile Fields Requested", requirements.profile_fields)
    render_screening_questions("Screening Questions", requirements.screening_questions)
    render_form_fields("Custom Form Fields", requirements.custom_form_fields)

    if requirements.motivation_letter:
        render_requirement_findings(
            "Motivation / Cover Letter",
            [requirements.motivation_letter],
        )

    render_requirement_findings("Consent Requirements", requirements.consent_requirements)
    render_requirement_findings(
        "Privacy, Login, and ATS Gates",
        requirements.privacy_login_ats_gates,
    )
    render_requirement_findings("Deadlines", requirements.deadlines)
    render_requirement_findings("Contact / Fallback Info", requirements.contact_or_fallback)

    if requirements.missing_or_uncertain:
        st.markdown("**Missing Or Uncertain**")
        for item in requirements.missing_or_uncertain:
            st.write(f"- {item}")

    if requirements.source_evidence:
        with st.expander("Source Evidence", expanded=False):
            for evidence in requirements.source_evidence:
                st.write(f"- {evidence}")


def render_requirement_findings(
    label: str,
    findings: list,
) -> None:
    if not findings:
        return
    st.markdown(f"**{label}**")
    for finding in findings:
        required = "required" if finding.required else "optional or unclear"
        constraints = (
            f" Constraints: {', '.join(finding.constraints)}" if finding.constraints else ""
        )
        st.write(f"- {finding.label} ({required}, confidence: {finding.confidence}).{constraints}")
        if finding.evidence:
            st.caption(finding.evidence)


def render_form_fields(label: str, fields: list) -> None:
    if not fields:
        return
    st.markdown(f"**{label}**")
    for field in fields:
        required = "required" if field.required else "optional or unclear"
        options = f" Options: {', '.join(field.options)}" if field.options else ""
        st.write(
            f"- {field.label} ({field.input_type or 'field'}, {required}, "
            f"confidence: {field.confidence}).{options}"
        )
        if field.evidence:
            st.caption(field.evidence)


def render_screening_questions(
    label: str,
    questions: list,
) -> None:
    if not questions:
        return
    st.markdown(f"**{label}**")
    for question in questions:
        required = "required" if question.required else "optional or unclear"
        st.write(
            f"- {question.question} ({question.input_type or 'field'}, {required}, "
            f"confidence: {question.confidence})"
        )
        if question.evidence:
            st.caption(question.evidence)


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
                apply_resolution = resolve_apply_url_from_url(
                    source_url,
                    title=extracted.title,
                    company=extracted.company,
                )
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
            return
        st.session_state["job_intake_source_url"] = source_url.strip()
        st.session_state["job_intake_extracted"] = extracted.model_dump(mode="json")
        st.session_state["job_intake_apply_resolution"] = apply_resolution.model_dump(mode="json")
        st.rerun()

    extracted_payload = st.session_state.get("job_intake_extracted")
    if not extracted_payload:
        return

    extracted_data = ExtractedJobData.model_validate(extracted_payload)
    apply_resolution_payload = st.session_state.get("job_intake_apply_resolution")
    apply_resolution = (
        ApplyUrlResolution.model_validate(apply_resolution_payload)
        if apply_resolution_payload
        else None
    )
    source_url = st.session_state.get("job_intake_source_url", "")
    st.subheader("Review Extracted Data")
    st.caption("Review what the AI found before adding it to the application workflow.")

    final_apply_url = choose_valid_apply_url(
        source_url,
        apply_resolution.apply_url if apply_resolution else "",
        extracted_data.apply_url,
    )
    if apply_resolution and apply_resolution.status != "resolved" and not final_apply_url:
        message = apply_resolution.notes or (
            "The application destination could not be verified automatically."
        )
        st.warning(message)

    with st.form("job_review_form"):
        left, right = st.columns(2)
        with left:
            title = st.text_input("Title", value=extracted_data.title)
            company = st.text_input("Company", value=extracted_data.company)
            location = st.text_input("Location", value=extracted_data.location)
            remote_policy = st.text_input("Remote Policy", value=extracted_data.remote_policy)
        with right:
            apply_url = st.text_input("Apply URL", value=final_apply_url)
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
        if extracted_data.apply_url:
            try:
                validate_apply_url(extracted_data.apply_url, source_url)
            except ValueError as exc:
                st.error(str(exc))

        save_submitted = st.form_submit_button("Add To Application Workflow")
        clear_submitted = st.form_submit_button("Start Over")

    if clear_submitted:
        st.session_state.pop("job_intake_source_url", None)
        st.session_state.pop("job_intake_extracted", None)
        st.session_state.pop("job_intake_apply_resolution", None)
        st.rerun()

    if not save_submitted:
        return

    try:
        dynamic_fields = [field for field in dynamic_fields if field["name"] or field["value"]]
        validate_apply_url(apply_url, source_url)
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
    st.session_state.pop("job_intake_apply_resolution", None)
    st.session_state["job_intake_success"] = (
        f"Added {job_listing.company} / {job_listing.title} to the workflow."
    )
    st.rerun()


def lines_from_text(value: str) -> list[str]:
    return [line.strip("-• \t") for line in value.splitlines() if line.strip("-• \t")]


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
