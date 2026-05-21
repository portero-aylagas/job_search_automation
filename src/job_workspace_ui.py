"""Streamlit UI for saved jobs, requirements, and application packages."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.app_workflow import (
    get_application_package_blockers,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_normalized_job,
    mark_requirements_reviewed,
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
from src.browser_use_launcher import (
    BrowserUseLaunchError,
    get_active_browser_use_session,
    open_apply_url_with_browser_use_candidate_agent,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.paths import RUNTIME_DATA_DIR
from src.schemas import (
    ApplicationPackage,
    ApplicationRequirements,
    JobListing,
    TrackerRecord,
)
from src.ui_components import (
    render_additional_details,
    render_ai_usage_summary,
    render_artifact_traceability,
    render_field,
    render_form_fields,
    render_list,
    render_requirement_findings,
    render_screening_questions,
    render_workflow_trace,
)


def render_jobs_page(base_dir: Path, tracker_records: list[TrackerRecord]) -> None:
    """Render saved jobs and their per-job workflow panels."""

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
    render_apply_assistance_panel(base_dir, job_listing)


def job_option_label(record: TrackerRecord) -> str:
    """Return the display label for a job selector option."""

    return f"{record.company} / {record.title}"


def render_tracker_job_summary(record: TrackerRecord) -> None:
    """Render fallback tracker-only job details when full intake data is missing."""

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
    """Render reviewed normalized job-intake data."""

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
    """Render requirements discovery, review status, and save actions."""

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
    """Render application package generation and review controls."""

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


def render_apply_assistance_panel(base_dir: Path, job: JobListing) -> None:
    """Render the first apply-assistance action for a reviewed job workspace."""

    st.divider()
    st.subheader("Apply Assistance")
    requirements = load_application_requirements(base_dir, job.id)
    candidate_profile = load_candidate_profile(base_dir)
    package = load_application_package(base_dir, job.id)
    browser_use_log_dir = Path(base_dir) / RUNTIME_DATA_DIR / "browser_use"
    blockers = get_apply_assistance_blockers(job, requirements, package)

    if blockers:
        st.warning("Apply assistance is blocked until these review steps are complete:")
        for blocker in blockers:
            st.write(f"- {blocker}")

    active_session = get_active_browser_use_session(browser_use_log_dir)
    if active_session is None:
        st.caption("Browser Use session status: idle.")
    else:
        st.info(
            "Browser Use session running: "
            f"PID {active_session.pid} for {active_session.url}"
        )
        st.caption(
            f"Started: {active_session.started_at}. "
            f"Log: {active_session.log_path}"
        )
        if st.button("Stop Browser Use Session", key=f"stop_browser_use_session_{job.id}"):
            stopped = stop_browser_use_session(browser_use_log_dir)
            if stopped:
                st.success("Stopped the active Browser Use session.")
                st.rerun()
            st.warning("No active Browser Use session was found.")

    if st.button("Kill All Browser Use Processes", key=f"kill_all_browser_use_{job.id}"):
        stopped_count = stop_all_browser_use_processes(browser_use_log_dir)
        st.success(f"Killed {stopped_count} Browser Use process group(s).")
        st.rerun()

    st.caption(
        "This action opens the reviewed apply URL and asks Browser Use to fill the form "
        "with fake test data and try the saved CV upload."
    )
    if st.button("Apply To Job", disabled=bool(blockers)):
        if blockers:
            st.error("Complete the required review steps before opening the apply flow.")
            return
        try:
            with st.spinner("Starting Browser Use apply agent..."):
                result = open_apply_url_with_browser_use_candidate_agent(
                    str(job.apply_url),
                    candidate_profile=candidate_profile,
                    log_dir=browser_use_log_dir,
                )
        except BrowserUseLaunchError as exc:
            st.error(str(exc))
            return

        st.success(f"Started Browser Use apply agent for {result.url}.")
        st.caption(f"Process ID: {result.pid}. Log: {result.log_path}")


def render_application_package_recovery_actions(
    base_dir: Path,
    job: JobListing,
    package: ApplicationPackage,
) -> ApplicationPackage:
    """Render package edit/reject actions and return the current package state."""

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
    """Render a generated application package for human review."""

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


def render_application_requirements(requirements: ApplicationRequirements) -> None:
    """Render interpreted application requirements and source evidence."""

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


def get_apply_assistance_blockers(
    job: JobListing,
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
) -> list[str]:
    """Return blockers that prevent opening the apply page from the Jobs workspace."""

    blockers: list[str] = []
    if job.apply_url is None:
        blockers.append("Resolve and save a valid apply URL.")

    if requirements is None:
        blockers.append("Discover application requirements for this apply URL.")
    elif requirements.status != "discovered" or not requirements.job_preserving:
        blockers.append("Resolve reviewed application requirements before applying.")
    elif requirements.review_status != "reviewed":
        blockers.append("Review the discovered application requirements.")

    if package is None:
        blockers.append("Generate the application package before applying.")
    elif package.status == "rejected":
        blockers.append("Regenerate or manually edit the rejected application package.")

    return blockers


def render_requirements_review_actions(
    base_dir: Path,
    requirements: ApplicationRequirements,
) -> None:
    """Render the action that marks discovered requirements as reviewed."""

    if requirements.status != "discovered" or requirements.review_status == "reviewed":
        return

    if st.button("Mark Requirements Reviewed"):
        reviewed_requirements = mark_requirements_reviewed(requirements)
        save_application_requirements(base_dir, reviewed_requirements)
        st.success("Requirements were marked as reviewed.")
        st.rerun()
