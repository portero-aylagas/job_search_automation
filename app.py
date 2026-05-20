from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.app_workflow import (
    apply_resolution_details,
    apply_url_review_messages,
    get_application_package_blockers,
    lines_from_text,
    load_app_data,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_normalized_job,
    mark_requirements_reviewed,
    resolved_apply_url,
    save_candidate_profile,
    validate_reviewed_apply_url,
    workflow_trace_payload,
)
from src.application_package import (
    apply_manual_artifact_edits,
    generate_application_package,
    load_application_package,
    reject_application_package,
    save_application_package,
    update_tracker_for_application_package,
)
from src.application_requirements import (
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.apply_url_resolution import resolve_apply_url_agentically
from src.candidate_profile import (
    merge_supplemental_extracted_data,
    validate_candidate_profile,
)
from src.cv_extraction import (
    run_cv_extraction_task,
    run_optional_document_extraction_task,
    save_uploaded_cv,
    save_uploaded_optional_document,
)
from src.job_intake import (
    create_job_listing,
    persist_job_listing,
)
from src.llm_job_extraction import (
    ApplyUrlResolution,
    ExtractedJobData,
    extract_job_data_from_url,
)
from src.schemas import (
    AIWorkflowTrace,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateOptionalDocument,
    CandidateProfile,
    JobListing,
    TrackerRecord,
)

BASE_DIR = Path(__file__).resolve().parent
EMPLOYMENT_TYPE_OPTIONS = [
    ("full_time", "Full-time"),
    ("part_time", "Part-time"),
    ("contract", "Contract"),
    ("freelance", "Freelance"),
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
OPTIONAL_DOCUMENT_TYPES = {
    "reference": "Reference",
    "certificate": "Certificate",
    "other": "Other document",
}
OPTIONAL_DOCUMENT_UPLOAD_MENUS = [
    ("reference", "Upload references"),
    ("certificate", "Upload certificates"),
    ("other", "Upload other documents"),
]
OPTIONAL_DOCUMENT_FILE_TYPES = ["pdf", "txt", "md", "docx"]
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


@dataclass(frozen=True)
class JobReviewFormState:
    title: str
    company: str
    location: str
    remote_policy: str
    apply_url: str
    salary: str
    posted_date: str
    source_job_id: str
    description: str
    requirements: str
    responsibilities: str
    nice_to_have_skills: str
    dynamic_fields: list[dict[str, object]]
    save_submitted: bool
    clear_submitted: bool


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
    render_optional_documents_section(base_dir, candidate_profile)
    render_cv_extracted_review_section(candidate_profile)
    render_candidate_preferences_section(candidate_profile)
    render_profile_save_section(base_dir, candidate_profile)


def render_cv_upload_section(base_dir: Path, candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("1. CV Upload")
        st.caption("The CV is the source of truth for professional data.")
        current_cv = candidate_profile.candidate_profile.source_documents.cv
        if current_cv.file_path:
            status = "parsed" if current_cv.parsed else "uploaded, not parsed"
            st.caption(f"Current CV: {Path(current_cv.file_path).name} ({status})")

        uploaded_cv = st.file_uploader(
            required_label("Upload CV"),
            type=["pdf", "txt", "md"],
            accept_multiple_files=False,
            key="candidate_profile_cv_upload",
        )
        if uploaded_cv is not None:
            st.caption(f"Selected file: {uploaded_cv.name}")

        st.caption(
            "This action uploads the CV to the AI provider and parses it into review fields."
        )
        if st.button("Parse CV", type="primary"):
            if uploaded_cv is None:
                st.error("Upload a CV before parsing.")
                return

            saved_path = save_uploaded_cv(base_dir, uploaded_cv.name, uploaded_cv.getvalue())
            try:
                with st.spinner("Parsing CV with the AI extractor..."):
                    extracted = run_cv_extraction_task(saved_path)
            except Exception as exc:
                st.error(format_cv_parse_error(saved_path, exc))
                return

            updated_profile = candidate_profile.model_copy(deep=True)
            updated_profile.candidate_profile.source_documents.cv.file_path = str(saved_path)
            updated_profile.candidate_profile.source_documents.cv.parsed = True
            updated_profile.candidate_profile.cv_extracted = extracted
            set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
            st.success("CV parsed and loaded into the review form.")
            st.rerun()


def format_cv_parse_error(saved_path: Path, exc: Exception) -> str:
    return (
        f"CV upload was saved to {saved_path}, but AI parsing failed: {exc}. "
        "Check that the Streamlit process has OPENAI_API_KEY and network access, "
        "then click Parse CV again."
    )


def render_optional_documents_section(base_dir: Path, candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("2. Optional documents")
        st.caption("Upload references, certificates, or other supporting documents.")

        existing_documents = candidate_profile.candidate_profile.source_documents.optional_documents
        if existing_documents:
            st.markdown("**Uploaded optional documents**")
            for document in existing_documents:
                status = "parsed" if document.parsed else "not parsed"
                document_type = OPTIONAL_DOCUMENT_TYPES.get(
                    document.document_type,
                    OPTIONAL_DOCUMENT_TYPES["other"],
                )
                st.caption(f"{document.file_name} - {document_type}, {status}")

        uploaded_documents_by_type = {}
        for document_type, label in OPTIONAL_DOCUMENT_UPLOAD_MENUS:
            uploaded_documents_by_type[document_type] = st.file_uploader(
                label,
                type=OPTIONAL_DOCUMENT_FILE_TYPES,
                accept_multiple_files=True,
                key=f"candidate_profile_optional_documents_upload_{document_type}",
            )

        st.caption("This action uploads each selected document to the AI provider for parsing.")
        if st.button("Upload and parse optional documents"):
            uploaded_document_entries = [
                (document_type, uploaded_document)
                for document_type, uploaded_documents in uploaded_documents_by_type.items()
                for uploaded_document in uploaded_documents or []
            ]
            if not uploaded_document_entries:
                st.error("Upload at least one optional document before parsing.")
                return

            updated_profile = candidate_profile.model_copy(deep=True)
            parsed_count = 0
            for document_type, uploaded_document in uploaded_document_entries:
                saved_path = save_uploaded_optional_document(
                    base_dir,
                    uploaded_document.name,
                    uploaded_document.getvalue(),
                )
                document = CandidateOptionalDocument(
                    file_path=str(saved_path),
                    file_name=uploaded_document.name,
                    document_type=document_type,
                    parsed=False,
                )

                try:
                    extracted = run_optional_document_extraction_task(saved_path)
                except Exception as exc:
                    updated_profile.candidate_profile.source_documents.optional_documents.append(
                        document
                    )
                    st.error(f"{uploaded_document.name}: {exc}")
                    continue

                merge_supplemental_extracted_data(
                    updated_profile.candidate_profile.cv_extracted,
                    extracted,
                )
                document.parsed = True
                updated_profile.candidate_profile.source_documents.optional_documents.append(
                    document
                )
                parsed_count += 1

            set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
            if parsed_count:
                st.success(
                    f"Parsed {parsed_count} optional document"
                    f"{'' if parsed_count == 1 else 's'} into the review fields."
                )
            st.rerun()


def render_cv_extracted_review_section(candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("3. Extracted data review")
        profile_data = candidate_profile.candidate_profile
        extracted = profile_data.cv_extracted

        if not profile_data.source_documents.cv.parsed:
            st.info("Upload and parse a CV to populate these review fields.")
        render_ai_usage_summary(
            "CV AI Usage Summary",
            [extracted.workflow_trace],
        )
        render_workflow_trace("CV Extraction Trace", extracted.workflow_trace)

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
            references = st.text_area(
                "References",
                value="\n".join(extracted.references),
                height=80,
            )

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
        updated_profile.candidate_profile.cv_extracted.references = lines_from_text(references)
        set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
        st.success("CV review fields updated.")
        st.rerun()


def render_candidate_preferences_section(candidate_profile: CandidateProfile) -> None:
    with st.container(border=True):
        st.subheader("4. Manual candidate preferences")
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
        type_columns = st.columns(2)
        for index, (value, label) in enumerate(EMPLOYMENT_TYPE_OPTIONS):
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


def get_latest_candidate_profile(base_dir: Path) -> CandidateProfile:
    return CandidateProfile.model_validate(get_candidate_profile_draft(base_dir))


def render_profile_save_section(base_dir: Path, _candidate_profile: CandidateProfile) -> None:
    st.subheader("Save")
    st.caption("This writes the reviewed profile to data/candidate_profile.json.")
    if st.button("Save profile", type="primary"):
        current_profile = get_latest_candidate_profile(base_dir)
        validation_errors = validate_candidate_profile(current_profile)
        if validation_errors:
            st.error("Missing required fields: " + ", ".join(validation_errors))
            return

        saved_path = save_candidate_profile(base_dir, current_profile)
        set_candidate_profile_draft(current_profile.model_dump(mode="json"))
        st.session_state["candidate_profile_success"] = f"Saved to {saved_path}."
        st.rerun()


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
    render_application_package_panel(base_dir, job_listing)


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

    st.caption("This action fetches the apply page and uses AI to interpret requirements.")
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

    render_ai_usage_summary(
        "Requirements AI Usage Summary",
        [requirements.workflow_trace],
    )
    render_application_requirements(requirements)
    render_requirements_review_actions(base_dir, requirements)


def render_application_package_panel(base_dir: Path, job: JobListing) -> None:
    st.divider()
    st.subheader("Application Package")
    package = load_application_package(base_dir, job.id)
    requirements = load_application_requirements(base_dir, job.id)
    candidate_profile = load_candidate_profile(base_dir)
    experience_units = load_experience_units(base_dir)

    package_blockers = get_application_package_blockers(candidate_profile, job, requirements)
    if package_blockers:
        st.warning(
            "Application package generation is blocked until these prerequisites are complete:"
        )
        for blocker in package_blockers:
            st.write(f"- {blocker}")

    st.caption("This action uses AI to draft application materials from reviewed data.")
    if st.button("Generate Application Package", disabled=bool(package_blockers)):
        if package_blockers:
            st.error("Complete all package prerequisites before generating application material.")
            return
        try:
            with st.spinner("Generating application package..."):
                package = generate_application_package(
                    candidate_profile,
                    experience_units,
                    job,
                    requirements,
                )
                json_path, markdown_path = save_application_package(base_dir, package, job)
                update_tracker_for_application_package(base_dir, job.id, json_path)
        except RuntimeError as exc:
            st.error(str(exc))
            return
        st.success(f"Application package saved. Markdown export: {markdown_path}")

    if package is None:
        st.info("No application package has been generated yet.")
        return

    render_ai_usage_summary(
        "Package AI Usage Summary",
        [package.workflow_trace],
    )
    package = render_application_package_recovery_actions(base_dir, job, package)
    render_application_package(package)


def render_application_package_recovery_actions(
    base_dir: Path,
    job: JobListing,
    package: ApplicationPackage,
) -> ApplicationPackage:
    with st.expander("Edit or reject generated package", expanded=False):
        with st.form(f"application_package_edit_form_{job.id}"):
            edited_content = {
                artifact.id: st.text_area(
                    artifact.label,
                    value=artifact.content,
                    key=f"application_package_edit_{job.id}_{artifact.id}",
                )
                for artifact in package.artifacts
            }
            save_edits = st.form_submit_button("Save manual edits")

        rejection_reason = st.text_area(
            "Rejection reason",
            key=f"application_package_reject_reason_{job.id}",
        )
        reject_package = st.button(
            "Reject package",
            key=f"application_package_reject_{job.id}",
        )

    if save_edits:
        edited_package = apply_manual_artifact_edits(package, edited_content)
        json_path, markdown_path = save_application_package(base_dir, edited_package, job)
        update_tracker_for_application_package(base_dir, job.id, json_path)
        st.success(f"Manual edits saved. Markdown export: {markdown_path}")
        return edited_package

    if reject_package:
        rejected_package = reject_application_package(package, rejection_reason)
        json_path, markdown_path = save_application_package(base_dir, rejected_package, job)
        update_tracker_for_application_package(base_dir, job.id, json_path)
        st.warning(f"Package rejected and saved. Markdown export: {markdown_path}")
        return rejected_package

    return package


def render_application_package(package: ApplicationPackage) -> None:
    status_columns = st.columns(3)
    status_columns[0].metric("Status", package.status)
    status_columns[1].metric("Artifacts", len(package.artifacts))
    status_columns[2].metric("Missing Items", len(package.missing_information))

    if package.selected_experience_units:
        render_list("Selected Experience Units", package.selected_experience_units)

    render_workflow_trace("Package Generation Trace", package.workflow_trace)

    if package.missing_information:
        st.markdown("**Missing Information**")
        for item in package.missing_information:
            st.write(f"- {item}")

    for artifact in package.artifacts:
        with st.expander(artifact.label, expanded=artifact.required):
            artifact_columns = st.columns(3)
            artifact_columns[0].metric("Type", artifact.type)
            artifact_columns[1].metric("Status", artifact.status)
            artifact_columns[2].metric(
                "Required",
                "Yes" if artifact.required else "No",
            )
            if artifact.source_prompt:
                st.markdown("**Source Prompt**")
                st.write(artifact.source_prompt)
            if artifact.source_requirement:
                st.markdown("**Source Requirement**")
                st.caption(artifact.source_requirement)
            render_artifact_traceability(artifact.metadata)
            st.markdown("**Content**")
            st.write(artifact.content or "No content generated.")

    if package.generation_notes:
        render_list("Generation Notes", package.generation_notes)


def render_artifact_traceability(metadata: dict[str, object]) -> None:
    traceability = metadata.get("traceability")
    if not isinstance(traceability, dict):
        return

    source_requirements = traceability.get("source_requirements")
    source_experience_units = traceability.get("source_experience_units")
    if not source_requirements and not source_experience_units:
        return

    st.markdown("**Traceability**")
    if isinstance(source_requirements, list) and source_requirements:
        st.caption("Source requirements")
        for requirement in source_requirements:
            if not isinstance(requirement, dict):
                continue
            label = requirement.get("label") or requirement.get("evidence") or "Requirement"
            confidence = requirement.get("confidence") or "unknown"
            st.write(f"- {label} (confidence: {confidence})")
            if requirement.get("evidence"):
                st.caption(str(requirement["evidence"]))

    if isinstance(source_experience_units, list) and source_experience_units:
        st.caption("Source experience")
        for experience in source_experience_units:
            if not isinstance(experience, dict):
                continue
            label = experience.get("title") or experience.get("id") or "Experience"
            organization = experience.get("organization")
            st.write(f"- {label}{f' / {organization}' if organization else ''}")


def render_application_requirements(requirements: ApplicationRequirements) -> None:
    status_columns = st.columns(4)
    status_columns[0].metric("Status", requirements.status)
    status_columns[1].metric("Review", requirements.review_status)
    status_columns[2].metric("Job Preserving", "Yes" if requirements.job_preserving else "No")
    status_columns[3].metric("Confidence", requirements.confidence)

    if requirements.blocked_reason:
        st.warning(requirements.blocked_reason)

    render_workflow_trace("Requirements Extraction Trace", requirements.workflow_trace)

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


def render_requirements_review_actions(
    base_dir: Path,
    requirements: ApplicationRequirements,
) -> None:
    if requirements.status != "discovered" or requirements.review_status == "reviewed":
        return

    if st.button("Mark Requirements Reviewed"):
        reviewed_requirements = mark_requirements_reviewed(requirements)
        save_application_requirements(base_dir, reviewed_requirements)
        st.success("Requirements were marked as reviewed.")
        st.rerun()


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


def build_ai_usage_summary(
    traces: list[AIWorkflowTrace | None],
) -> dict[str, int]:
    active_traces = [trace for trace in traces if trace is not None]
    return {
        "call_count": len(active_traces),
        "attempt_count": sum(trace.attempt_count for trace in active_traces),
        "retry_count": sum(max(trace.attempt_count - 1, 0) for trace in active_traces),
        "output_token_budget": sum(
            trace.max_output_tokens * trace.attempt_count for trace in active_traces
        ),
        "worst_case_output_token_budget": sum(
            trace.max_output_tokens * (trace.max_retries + 1) for trace in active_traces
        ),
        "tool_call_cap": sum(trace.max_tool_calls or 0 for trace in active_traces),
    }


def render_ai_usage_summary(label: str, traces: list[AIWorkflowTrace | None]) -> None:
    summary = build_ai_usage_summary(traces)
    if summary["call_count"] == 0:
        return

    with st.expander(label, expanded=False):
        st.write(f"AI calls: {summary['call_count']}")
        st.write(f"Provider attempts: {summary['attempt_count']}")
        st.write(f"Retries used: {summary['retry_count']}")
        st.write(f"Output token budget used by attempts: {summary['output_token_budget']}")
        st.write(
            "Worst-case output token budget with configured retries: "
            f"{summary['worst_case_output_token_budget']}"
        )
        st.write(f"Tool call cap: {summary['tool_call_cap'] or 'none'}")


def render_workflow_trace(label: str, trace: AIWorkflowTrace | None) -> None:
    if trace is None:
        return

    with st.expander(label, expanded=False):
        st.write(f"Workflow: {trace.workflow_name}")
        st.write(f"Operation: {trace.operation}")
        st.write(f"Model: {trace.model}")
        st.write(f"Profile: {trace.profile_name}")
        st.write(f"Temperature: {trace.temperature}")
        st.write(f"Max output tokens: {trace.max_output_tokens}")
        st.write(f"Timeout seconds: {trace.timeout_seconds}")
        st.write(f"Retries allowed: {trace.max_retries}")
        st.write(f"Retry backoff seconds: {trace.retry_backoff_seconds}")
        st.write(f"Tool call cap: {trace.max_tool_calls or 'none'}")
        st.write(f"Attempt count: {trace.attempt_count}")
        st.write(f"Duration (ms): {trace.duration_ms or 0}")
        st.caption(f"Recorded at {trace.recorded_at}")


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


def render_job_url_extraction_form() -> tuple[bool, str]:
    with st.form("job_url_form"):
        source_url = st.text_input("Job URL", placeholder="https://company.com/jobs/role")
        st.caption("This action uses AI and may perform web search to resolve the apply URL.")
        extract_submitted = st.form_submit_button("Extract Application Data")
    return extract_submitted, source_url


def handle_job_url_extraction(source_url: str) -> bool:
    try:
        with st.spinner("Extracting job data with AI..."):
            extracted = extract_job_data_from_url(source_url)
            apply_resolution = resolve_apply_url_agentically(
                source_url,
                title=extracted.title,
                company=extracted.company,
                source_job_id=extracted.source_job_id,
            )
    except (RuntimeError, ValueError) as exc:
        st.error(str(exc))
        return False

    st.session_state["job_intake_source_url"] = source_url.strip()
    st.session_state["job_intake_extracted"] = extracted.model_dump(mode="json")
    st.session_state["job_intake_apply_resolution"] = apply_resolution.model_dump(mode="json")
    return True


def load_job_intake_review_state() -> (
    tuple[ExtractedJobData, ApplyUrlResolution | None, str] | None
):
    extracted_payload = st.session_state.get("job_intake_extracted")
    if not extracted_payload:
        return None

    extracted_data = ExtractedJobData.model_validate(extracted_payload)
    apply_resolution_payload = st.session_state.get("job_intake_apply_resolution")
    apply_resolution = (
        ApplyUrlResolution.model_validate(apply_resolution_payload)
        if apply_resolution_payload
        else None
    )
    source_url = st.session_state.get("job_intake_source_url", "")
    return extracted_data, apply_resolution, source_url


def render_job_intake_review_header(
    extracted_data: ExtractedJobData,
    apply_resolution: ApplyUrlResolution | None,
    source_url: str,
) -> str:
    st.subheader("Review Extracted Data")
    st.caption("Review what the AI found before adding it to the application workflow.")
    render_ai_usage_summary(
        "Job Intake AI Usage Summary",
        [
            extracted_data.workflow_trace,
            apply_resolution.workflow_trace if apply_resolution else None,
        ],
    )
    render_workflow_trace("Job Extraction Trace", extracted_data.workflow_trace)
    render_workflow_trace(
        "Apply URL Resolution Trace",
        apply_resolution.workflow_trace if apply_resolution else None,
    )

    final_apply_url = resolved_apply_url(source_url, apply_resolution)
    if apply_resolution and apply_resolution.status != "resolved":
        message = apply_resolution.notes or (
            "The application destination could not be verified automatically."
        )
        st.warning(message)
    return final_apply_url


def render_job_review_form(
    extracted_data: ExtractedJobData,
    source_url: str,
    final_apply_url: str,
) -> JobReviewFormState:
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
        apply_url_messages = apply_url_review_messages(
            extracted_data.apply_url,
            source_url,
            final_apply_url,
        )
        for message in apply_url_messages["errors"]:
            st.error(message)
        for message in apply_url_messages["warnings"]:
            st.warning(message)
        for message in apply_url_messages["info"]:
            st.info(message)

        save_submitted = st.form_submit_button("Add To Application Workflow")
        clear_submitted = st.form_submit_button("Start Over")

    return JobReviewFormState(
        title=title,
        company=company,
        location=location,
        remote_policy=remote_policy,
        apply_url=apply_url,
        salary=salary,
        posted_date=posted_date,
        source_job_id=source_job_id,
        description=description,
        requirements=requirements,
        responsibilities=responsibilities,
        nice_to_have_skills=nice_to_have_skills,
        dynamic_fields=dynamic_fields,
        save_submitted=save_submitted,
        clear_submitted=clear_submitted,
    )


def build_reviewed_job_listing(
    form_state: JobReviewFormState,
    extracted_data: ExtractedJobData,
    source_url: str,
    apply_resolution: ApplyUrlResolution | None,
) -> JobListing:
    dynamic_fields = [
        field for field in form_state.dynamic_fields if field["name"] or field["value"]
    ]
    validate_reviewed_apply_url(form_state.apply_url, source_url, apply_resolution)
    return create_job_listing(
        title=form_state.title,
        company=form_state.company,
        source_url=source_url,
        location=form_state.location,
        remote_policy=form_state.remote_policy,
        apply_url=form_state.apply_url,
        description=form_state.description,
        requirements=lines_from_text(form_state.requirements),
        responsibilities=lines_from_text(form_state.responsibilities),
        nice_to_have_skills=lines_from_text(form_state.nice_to_have_skills),
        salary=form_state.salary,
        posted_date=form_state.posted_date,
        source_job_id=form_state.source_job_id,
        job_details={
            "extraction_confidence": extracted_data.confidence,
            "job_extraction_trace": workflow_trace_payload(extracted_data.workflow_trace),
            "apply_url_resolution": apply_resolution_details(
                form_state.apply_url,
                source_url,
                apply_resolution,
            ),
            "dynamic_fields": dynamic_fields,
        },
    )


def clear_job_intake_session_state() -> None:
    st.session_state.pop("job_intake_source_url", None)
    st.session_state.pop("job_intake_extracted", None)
    st.session_state.pop("job_intake_apply_resolution", None)


def render_job_intake_page(base_dir: Path) -> None:
    st.title("Job Intake")
    st.write("Generate application data from a job URL.")

    success_message = st.session_state.pop("job_intake_success", None)
    if success_message:
        st.success(success_message)

    extract_submitted, source_url = render_job_url_extraction_form()
    if extract_submitted:
        if handle_job_url_extraction(source_url):
            st.rerun()
        return

    review_state = load_job_intake_review_state()
    if review_state is None:
        return

    extracted_data, apply_resolution, source_url = review_state
    final_apply_url = render_job_intake_review_header(
        extracted_data,
        apply_resolution,
        source_url,
    )
    form_state = render_job_review_form(extracted_data, source_url, final_apply_url)

    if form_state.clear_submitted:
        clear_job_intake_session_state()
        st.rerun()

    if not form_state.save_submitted:
        return

    try:
        job_listing = build_reviewed_job_listing(
            form_state,
            extracted_data,
            source_url,
            apply_resolution,
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
    clear_job_intake_session_state()
    st.session_state["job_intake_success"] = (
        f"Added {job_listing.company} / {job_listing.title} to the workflow."
    )
    st.rerun()


def main() -> None:
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
