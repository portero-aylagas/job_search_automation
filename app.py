from __future__ import annotations

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.application_requirements import (
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.cv_extraction import run_cv_extraction_task, save_uploaded_cv
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
    JobListing,
    TrackerRecord,
)
from src.storage import load_model, save_model

BASE_DIR = Path(__file__).resolve().parent
EMPLOYMENT_TYPE_GROUPS = [
    (
        "Commitment",
        [
            ("full_time", "Full-time"),
            ("part_time", "Part-time"),
        ],
    ),
    (
        "Engagement",
        [
            ("contract", "Contract"),
            ("freelance", "Freelance"),
        ],
    ),
]
REMOTE_PREFERENCE_OPTIONS = [
    ("remote", "Remote"),
    ("hybrid", "Hybrid"),
    ("onsite", "On-site"),
]
WORK_AUTHORIZATION_OPTIONS = [
    ("eu_authorized", "EU authorized"),
    ("eu_sponsorship_required", "EU sponsorship required"),
]
CAREER_LEVEL_OPTIONS = [
    ("internship", "Internship"),
    ("working_student", "Working student"),
    ("trainee", "Trainee"),
    ("junior", "Junior"),
    ("entry_level", "Entry level"),
    ("mid_level", "Mid level"),
    ("senior", "Senior"),
    ("lead", "Lead"),
    ("principal", "Principal"),
    ("manager", "Manager"),
]
CAREER_LEVEL_HELP = {
    "internship": "Early training role, usually temporary and part of learning.",
    "working_student": "Student role with part-time professional work alongside studies.",
    "trainee": "Structured early-career role focused on learning the job.",
    "junior": "First professional role with limited experience and support.",
    "entry_level": "Starting role for someone entering the field.",
    "mid_level": "Independent contributor with solid practical experience.",
    "senior": "Experienced contributor who works with little supervision.",
    "lead": "Senior contributor who also guides delivery or other people.",
    "principal": "Expert individual contributor with broad technical depth.",
    "manager": "People or team leadership role.",
}


def load_app_data() -> tuple[CandidateProfile, list[TrackerRecord]]:
    bootstrap_sample_data(BASE_DIR)

    profile = load_candidate_profile(BASE_DIR)
    tracker_records = load_jobs_index(BASE_DIR)
    return profile, tracker_records


def load_candidate_profile(base_dir: Path) -> CandidateProfile:
    runtime_path = base_dir / "data" / "runtime" / "candidate_profile.json"
    template_path = base_dir / "data" / "candidate_profile.json"
    legacy_path = base_dir / "data" / "profile.json"

    if runtime_path.exists():
        return load_model(runtime_path, CandidateProfile)
    if template_path.exists():
        return load_model(template_path, CandidateProfile)
    if legacy_path.exists():
        return load_model(legacy_path, CandidateProfile)
    return CandidateProfile()


def save_candidate_profile(base_dir: Path, profile: CandidateProfile) -> Path:
    target = base_dir / "data" / "candidate_profile.json"
    save_model(target, profile)
    return target


def get_candidate_profile_draft(base_dir: Path) -> dict:
    draft = st.session_state.get("candidate_profile_draft")
    if draft is None:
        draft = load_candidate_profile(base_dir).model_dump(mode="json")
        st.session_state["candidate_profile_draft"] = draft
    return draft


def set_candidate_profile_draft(draft: dict) -> None:
    st.session_state["candidate_profile_draft"] = draft


def required_label(label: str) -> str:
    return f"{label} *"


def work_authorization_index(value: str) -> int | None:
    for index, (option_value, _) in enumerate(WORK_AUTHORIZATION_OPTIONS):
        if option_value == value:
            return index
    return None


def render_candidate_profile_page(base_dir: Path) -> None:
    st.title("Candidate Profile")
    st.write(
        "Upload your CV once, review the extracted data, and fill in the missing "
        "job-search preferences."
    )

    success_message = st.session_state.pop("candidate_profile_success", None)
    if success_message:
        st.success(success_message)

    draft = get_candidate_profile_draft(base_dir)
    candidate_profile = CandidateProfile.model_validate(draft)

    render_cv_upload_section(base_dir, candidate_profile)
    render_cv_extracted_review_section(candidate_profile)
    render_candidate_preferences_section(candidate_profile)
    render_profile_save_section(base_dir, candidate_profile)


def render_cv_upload_section(base_dir: Path, candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("1. CV Upload")
        st.caption("The CV is the source of truth for professional data.")

        uploaded_cv = st.file_uploader(
            required_label("Upload CV"),
            type=["pdf", "txt", "md"],
            accept_multiple_files=False,
            key="candidate_profile_cv_upload",
        )
        if uploaded_cv is not None:
            st.caption(f"Selected file: {uploaded_cv.name}")

        if st.button("Parse CV", type="primary"):
            if uploaded_cv is None:
                st.error("Upload a CV before parsing.")
                return

            saved_path = save_uploaded_cv(base_dir, uploaded_cv.name, uploaded_cv.getvalue())
            try:
                extracted = run_cv_extraction_task(saved_path)
            except Exception as exc:
                st.error(str(exc))
                return

            updated_profile = candidate_profile.model_copy(deep=True)
            updated_profile.candidate_profile.source_documents.cv.file_path = str(saved_path)
            updated_profile.candidate_profile.source_documents.cv.parsed = True
            updated_profile.candidate_profile.cv_extracted = extracted
            set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
            st.success("CV parsed and loaded into the review form.")
            st.rerun()


def render_cv_extracted_review_section(candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("2. CV-extracted data review")
        profile_data = candidate_profile.candidate_profile
        extracted = profile_data.cv_extracted

        if not profile_data.source_documents.cv.parsed:
            st.info("Upload and parse a CV to populate these review fields.")

        with st.form("candidate_profile_review_form"):
            st.markdown("**Identity**")
            identity_left, identity_right = st.columns(2)
            with identity_left:
                full_name = st.text_input(
                    required_label("Full name"),
                    value=extracted.identity.full_name,
                )
                email = st.text_input(required_label("Email"), value=extracted.identity.email)
                phone = st.text_input("Phone", value=extracted.identity.phone)
                location = st.text_input("Location", value=extracted.identity.location)
            with identity_right:
                linkedin_url = st.text_input(
                    "LinkedIn URL", value=extracted.identity.linkedin_url
                )
                github_url = st.text_input("GitHub URL", value=extracted.identity.github_url)
                portfolio_url = st.text_input(
                    "Portfolio URL", value=extracted.identity.portfolio_url
                )

            st.markdown("**Professional data**")
            work_experience = st.text_area(
                "Work experience",
                value="\n".join(extracted.work_experience),
                height=120,
            )
            education = st.text_area(
                "Education",
                value="\n".join(extracted.education),
                height=120,
            )
            skills = st.text_area("Skills", value="\n".join(extracted.skills), height=100)
            languages = st.text_area("Languages", value="\n".join(extracted.languages), height=80)
            certifications = st.text_area(
                "Certifications",
                value="\n".join(extracted.certifications),
                height=80,
            )
            projects = st.text_area("Projects", value="\n".join(extracted.projects), height=100)

            save_extracted = st.form_submit_button("Save CV review changes")

        if not save_extracted:
            return

        updated_profile = candidate_profile.model_copy(deep=True)
        updated_profile.candidate_profile.cv_extracted.identity.full_name = full_name.strip()
        updated_profile.candidate_profile.cv_extracted.identity.email = email.strip()
        updated_profile.candidate_profile.cv_extracted.identity.phone = phone.strip()
        updated_profile.candidate_profile.cv_extracted.identity.location = location.strip()
        updated_profile.candidate_profile.cv_extracted.identity.linkedin_url = linkedin_url.strip()
        updated_profile.candidate_profile.cv_extracted.identity.github_url = github_url.strip()
        updated_profile.candidate_profile.cv_extracted.identity.portfolio_url = (
            portfolio_url.strip()
        )
        updated_profile.candidate_profile.cv_extracted.work_experience = lines_from_text(
            work_experience
        )
        updated_profile.candidate_profile.cv_extracted.education = lines_from_text(education)
        updated_profile.candidate_profile.cv_extracted.skills = lines_from_text(skills)
        updated_profile.candidate_profile.cv_extracted.languages = lines_from_text(languages)
        updated_profile.candidate_profile.cv_extracted.certifications = lines_from_text(
            certifications
        )
        updated_profile.candidate_profile.cv_extracted.projects = lines_from_text(projects)
        set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
        st.success("CV review fields updated.")
        st.rerun()


def render_candidate_preferences_section(candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("3. Manual candidate preferences")
        profile_data = candidate_profile.candidate_profile
        preferences = profile_data.candidate_preferences

        target_roles = st.text_area(
            required_label("Target roles"),
            value="\n".join(preferences.target_roles),
            height=100,
        )
        target_locations = st.text_area(
            required_label("Target locations"),
            value="\n".join(preferences.target_locations),
            height=100,
        )
        st.markdown("**Remote preference** *")
        selected_remote_preferences: list[str] = []
        remote_preference_values = set(preferences.remote_preference)
        remote_columns = st.columns(2)
        for index, (value, label) in enumerate(REMOTE_PREFERENCE_OPTIONS):
            column = remote_columns[index % 2]
            with column:
                if st.checkbox(
                    label,
                    value=value in remote_preference_values,
                    key=f"remote_preference_{value}",
                ):
                    selected_remote_preferences.append(value)

        st.markdown("**Employment type** *")
        selected_employment_types: list[str] = []
        employment_type_values = set(preferences.employment_type)
        for group_label, group_options in EMPLOYMENT_TYPE_GROUPS:
            st.caption(group_label)
            type_columns = st.columns(2)
            for index, (value, label) in enumerate(group_options):
                column = type_columns[index % 2]
                with column:
                    if st.checkbox(
                        label,
                        value=value in employment_type_values,
                        key=f"employment_type_{value}",
                    ):
                        selected_employment_types.append(value)

        st.markdown("**Career level** *")
        selected_seniority_levels: list[str] = []
        seniority_level_values = set(preferences.seniority_level)
        seniority_columns = st.columns(2)
        for index, (value, label) in enumerate(CAREER_LEVEL_OPTIONS):
            column = seniority_columns[index % 2]
            with column:
                if st.checkbox(
                    label,
                    value=value in seniority_level_values,
                    help=CAREER_LEVEL_HELP.get(value),
                    key=f"seniority_level_{value}",
                ):
                    selected_seniority_levels.append(value)

        availability = st.text_input(required_label("Availability"), value=preferences.availability)
        work_authorization = st.radio(
            required_label("Work authorization"),
            options=[value for value, _ in WORK_AUTHORIZATION_OPTIONS],
            format_func=dict(WORK_AUTHORIZATION_OPTIONS).get,
            index=work_authorization_index(preferences.work_authorization),
            horizontal=True,
            key="candidate_profile_work_authorization",
        )
        salary_left, salary_right = st.columns(2)
        with salary_left:
            salary_min_eur = st.number_input(
                required_label("Salary min (EUR / year)"),
                min_value=0,
                step=1000,
                value=preferences.salary_min_eur or 50000,
                key="candidate_profile_salary_min_eur",
            )
        with salary_right:
            salary_max_eur = st.number_input(
                required_label("Salary max (EUR / year)"),
                min_value=0,
                step=1000,
                value=preferences.salary_max_eur or 100000,
                key="candidate_profile_salary_max_eur",
            )
        st.caption("Currency: EUR per year")

        updated_profile = candidate_profile.model_copy(deep=True)
        updated_profile.candidate_profile.candidate_preferences.target_roles = lines_from_text(
            target_roles
        )
        updated_profile.candidate_profile.candidate_preferences.target_locations = lines_from_text(
            target_locations
        )
        updated_profile.candidate_profile.candidate_preferences.remote_preference = (
            selected_remote_preferences
        )
        updated_profile.candidate_profile.candidate_preferences.employment_type = (
            selected_employment_types
        )
        updated_profile.candidate_profile.candidate_preferences.seniority_level = (
            selected_seniority_levels
        )
        updated_profile.candidate_profile.candidate_preferences.availability = availability.strip()
        updated_profile.candidate_profile.candidate_preferences.salary_min_eur = int(
            salary_min_eur
        )
        updated_profile.candidate_profile.candidate_preferences.salary_max_eur = int(
            salary_max_eur
        )
        updated_profile.candidate_profile.candidate_preferences.work_authorization = (
            work_authorization or ""
        )
        set_candidate_profile_draft(updated_profile.model_dump(mode="json"))


def render_profile_save_section(base_dir: Path, candidate_profile: CandidateProfile) -> None:
    st.subheader("Save")
    if st.button("Save profile", type="primary"):
        validation_errors = validate_candidate_profile(candidate_profile)
        if validation_errors:
            st.error("Missing required fields: " + ", ".join(validation_errors))
            return

        updated_profile = candidate_profile.model_copy(deep=True)
        saved_path = save_candidate_profile(base_dir, updated_profile)
        set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
        st.session_state["candidate_profile_success"] = f"Saved to {saved_path}."
        st.rerun()


def validate_candidate_profile(candidate_profile: CandidateProfile) -> list[str]:
    profile = candidate_profile.candidate_profile
    errors: list[str] = []

    if not profile.source_documents.cv.file_path.strip():
        errors.append("Upload CV")
    if not profile.cv_extracted.identity.full_name.strip():
        errors.append("Full name")
    if not profile.cv_extracted.identity.email.strip():
        errors.append("Email")
    if not profile.candidate_preferences.target_roles:
        errors.append("Target roles")
    if not profile.candidate_preferences.target_locations:
        errors.append("Target locations")
    if not profile.candidate_preferences.remote_preference:
        errors.append("Remote preference")
    if not profile.candidate_preferences.employment_type:
        errors.append("Employment type")
    if not profile.candidate_preferences.seniority_level:
        errors.append("Career level")
    if not profile.candidate_preferences.availability.strip():
        errors.append("Availability")
    if profile.candidate_preferences.salary_min_eur is None:
        errors.append("Salary min")
    if profile.candidate_preferences.salary_max_eur is None:
        errors.append("Salary max")
    if (
        profile.candidate_preferences.salary_min_eur is not None
        and profile.candidate_preferences.salary_max_eur is not None
        and (
            profile.candidate_preferences.salary_max_eur
            < profile.candidate_preferences.salary_min_eur
        )
    ):
        errors.append("Salary max must be >= Salary min")
    if not str(profile.candidate_preferences.work_authorization).strip():
        errors.append("Work authorization")

    return errors


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
    _, tracker_records = load_app_data()

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
