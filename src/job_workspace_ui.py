"""Streamlit UI for saved jobs, requirements, and application packages."""

from __future__ import annotations

import hashlib
from pathlib import Path

import streamlit as st

from src.app_workflow import (
    get_application_package_blockers,
    load_application_page_snapshot,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_normalized_job,
    mark_requirements_reviewed,
)
from src.application_fill_plan import (
    apply_fill_plan_edits,
    fill_plan_blocked_field_edit_key,
    fill_plan_field_edit_key,
    fill_plan_needs_answer_edit_key,
    fill_plan_upload_edit_key,
    generate_application_fill_plan,
    get_application_fill_plan_review_blockers,
    load_application_fill_plan,
    map_application_fields_with_llm,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.application_package import (
    apply_manual_artifact_edits,
    export_cover_letter_artifact,
    generate_application_package,
    load_application_package,
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
    open_apply_url_with_browser_use_fill_plan,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.paths import RUNTIME_DATA_DIR, application_package_artifacts_dir
from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    JobListing,
    TrackerRecord,
)
from src.ui_components import (
    AI_ACTION_COST_HELP,
    format_detail_value,
    render_additional_details,
    render_artifact_traceability,
    render_field,
    render_form_fields,
    render_list,
    render_optional_ai_details,
    render_requirement_findings,
    render_screening_questions,
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

    if job_listing is None:
        render_tracker_status_summary(selected_record)
        render_tracker_job_summary(selected_record)
        st.warning("Full intake data is not available for this job yet.")
        return

    with st.container(border=True):
        render_job_intake_summary(job_listing)
    with st.container(border=True):
        render_application_requirements_panel(base_dir, job_listing)
    with st.container(border=True):
        render_application_package_panel(base_dir, job_listing)
    with st.container(border=True):
        render_application_fill_plan_panel(base_dir, job_listing)
    with st.container(border=True):
        render_apply_to_position_panel(base_dir, job_listing)


def job_option_label(record: TrackerRecord) -> str:
    """Return the display label for a job selector option."""

    return f"{record.company} / {record.title}"


def format_match_score(record: TrackerRecord) -> str:
    """Return a compact match-score label for a tracker record."""

    if record.match_score is None:
        return "Not analyzed"
    return f"{record.match_score:g}"


def render_tracker_status_summary(record: TrackerRecord) -> None:
    """Render compact tracker status when only tracker data is available."""

    status_left, status_right, status_third = st.columns(3)
    status_left.metric("Status", record.status)
    status_right.metric("Match Score", format_match_score(record))
    status_third.metric("Retrieval", record.retrieval_mode)


def build_review_checklist(
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
) -> list[str]:
    """Build a de-duplicated list of human decisions still worth surfacing."""

    items: list[str] = []
    if requirements is not None:
        items.extend(requirement_review_labels(requirements))
    if package is not None:
        items.extend(package.missing_information)
    return [
        item
        for item in deduplicate_review_items(items)
        if not review_item_is_represented_in_fill_plan(item, fill_plan)
    ]


def review_item_is_represented_in_fill_plan(
    item: str,
    fill_plan: ApplicationFillPlan | None,
) -> bool:
    """Return whether a review item already appears as an editable fill-plan field."""

    if fill_plan is None:
        return False
    normalized_item = normalize_review_item(item)
    editable_labels = [
        field.label
        for field in [
            *fill_plan.field_values,
            *fill_plan.needs_answer_fields,
            *fill_plan.blocked_fields,
        ]
    ]
    return normalized_item in {
        normalize_review_item(label) for label in editable_labels if label.strip()
    }


def requirement_review_labels(requirements: ApplicationRequirements) -> list[str]:
    """Return concise labels for requirement groups that require human awareness."""

    labels: list[str] = []
    labels.extend(finding.label for finding in requirements.consent_requirements)
    labels.extend(question.question for question in requirements.screening_questions)
    labels.extend(field.label for field in requirements.custom_form_fields)
    labels.extend(requirements.missing_or_uncertain)
    return labels


def deduplicate_review_items(items: list[str]) -> list[str]:
    """Return review items without repeated labels across workflow artifacts."""

    seen: set[str] = set()
    deduplicated: list[str] = []
    for item in items:
        normalized_item = normalize_review_item(item)
        if not normalized_item or normalized_item in seen:
            continue
        seen.add(normalized_item)
        deduplicated.append(clean_review_item_label(item))
    return deduplicated


def normalize_review_item(item: str) -> str:
    """Normalize semantically repeated review labels for de-duplication."""

    normalized = clean_review_item_label(item).casefold()
    replacements = {
        "user decision required: ": "",
        "user must review consent requirement: ": "",
        "optional consent for ": "",
        "privacy policy acknowledgement": "privacy policy acknowledgment",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    if "schwerbehinderung" in normalized or "behinderung" in normalized:
        return "disability disclosure"
    if (
        "empfehlung" in normalized
        or "referral" in normalized
        or "recommendation code" in normalized
    ):
        return "employee referral"
    if "datenschutz" in normalized or "privacy policy" in normalized:
        return "privacy consent"
    if "firmengruppe" in normalized or "group companies" in normalized:
        return "group company data sharing"
    if "intern" in normalized or "internal" in normalized:
        return "internal application"
    if "zeugnisse" in normalized or "certificates" in normalized:
        return "certificates upload"
    if "deadline" in normalized or "application deadline" in normalized:
        return "application deadline"
    if "contact" in normalized or "recruiter" in normalized:
        return "fallback contact"
    return normalized


def clean_review_item_label(item: str) -> str:
    """Trim noisy prefixes from review items while preserving meaning."""

    cleaned = item.strip()
    prefixes = [
        "User decision required: ",
        "User must review consent requirement: ",
        "User should confirm ",
    ]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            return cleaned.removeprefix(prefix).strip()
    return cleaned


def render_review_checklist(
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
) -> None:
    """Render a single compact human-review checklist."""

    checklist = build_review_checklist(requirements, package, fill_plan)
    if not checklist:
        return
    with st.expander("Human review checklist", expanded=False):
        for item in checklist:
            st.write(f"- {item}")


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
    """Render a compact reviewed normalized job-intake summary."""

    st.subheader("Job Snapshot")
    left, right = st.columns(2)
    with left:
        render_field("Location", job.location)
        render_field("Remote Policy", job.remote_policy)
        render_field("Salary", job.salary)
    with right:
        render_field("Posted Date", job.posted_date)
        render_field("Source Job ID", job.source_job_id)
        st.markdown(f"[Source URL]({job.source_url})")
        if job.apply_url:
            st.markdown(f"[Apply URL]({job.apply_url})")

    if job.description:
        st.markdown("**Role Summary**")
        st.write(job.description)

    with st.expander("Role details", expanded=False):
        render_list("Requirements", job.requirements)
        render_list("Responsibilities", job.responsibilities)
        render_list("Nice-to-have Skills", job.nice_to_have_skills)

    with st.expander("Advanced job details", expanded=False):
        render_job_advanced_details(job)

    job_extraction_trace = get_job_extraction_trace(job)
    render_optional_ai_details(
        "job snapshot",
        [("Job Extraction Trace", job_extraction_trace)],
        summary_label="Job Intake AI Usage Summary",
        summary_traces=[job_extraction_trace],
    )


def get_job_extraction_trace(job: JobListing) -> AIWorkflowTrace | None:
    """Return the stored job extraction trace as workflow metadata when valid."""

    raw_trace = job.job_details.get("job_extraction_trace")
    if raw_trace is None:
        return None
    try:
        return AIWorkflowTrace.model_validate(raw_trace)
    except ValueError:
        return None


def render_job_advanced_details(job: JobListing) -> None:
    """Render lower-priority job extraction metadata and dynamic details."""

    dynamic_details = {"dynamic_fields": job.job_details.get("dynamic_fields", [])}
    render_additional_details(dynamic_details)

    extraction_confidence = job.job_details.get("extraction_confidence")
    if extraction_confidence:
        render_field("Extraction Confidence", str(extraction_confidence))

    apply_url_resolution = job.job_details.get("apply_url_resolution")
    if isinstance(apply_url_resolution, dict):
        render_apply_url_resolution_details(apply_url_resolution)

    remaining_details = {
        key: value
        for key, value in job.job_details.items()
        if key
        not in {
            "dynamic_fields",
            "extraction_confidence",
            "job_extraction_trace",
            "apply_url_resolution",
        }
        and value
    }
    if remaining_details:
        st.markdown("**Other Details**")
        for key, value in remaining_details.items():
            render_field(key.replace("_", " ").title(), format_detail_value(value))


def render_apply_url_resolution_details(resolution: dict[str, object]) -> None:
    """Render apply URL resolution details in the advanced job area."""

    st.markdown("**Apply URL Resolution**")
    for key in ["status", "confidence", "notes"]:
        value = resolution.get(key)
        if value:
            render_field(key.replace("_", " ").title(), str(value))
    evidence = resolution.get("evidence")
    if isinstance(evidence, list) and evidence:
        render_list("Evidence", [str(item) for item in evidence])


def render_application_requirements_panel(base_dir: Path, job: JobListing) -> None:
    """Render requirements discovery, review status, and save actions."""

    st.subheader("Application Requirements")
    requirements = load_application_requirements(base_dir, job.id)

    if job.apply_url is None:
        st.warning("Apply URL is missing. Requirements discovery is blocked.")
        return

    st.caption("This action fetches the apply page and uses AI to interpret requirements.")
    if st.button(
        "Discover requirements from apply URL with AI",
        type="primary",
        help=AI_ACTION_COST_HELP,
    ):
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
    render_optional_ai_details(
        "application requirements",
        [("Requirements Extraction Trace", requirements.workflow_trace)],
        summary_label="Requirements AI Usage Summary",
        summary_traces=[requirements.workflow_trace],
    )
    render_requirements_review_actions(base_dir, requirements)


def render_application_package_panel(base_dir: Path, job: JobListing) -> None:
    """Render application package generation and review controls."""

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
    if st.button(
        "Generate application package with AI",
        disabled=bool(package_blockers),
        type="primary",
        help=AI_ACTION_COST_HELP,
    ):
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

    package = render_application_package_review_form(base_dir, job, package)
    render_optional_ai_details(
        "application package",
        [("Package Generation Trace", package.workflow_trace)],
        summary_label="Package AI Usage Summary",
        summary_traces=[package.workflow_trace],
    )


def render_apply_to_position_panel(base_dir: Path, job: JobListing) -> None:
    """Render the final apply action box for one reviewed job workspace."""

    st.subheader("Apply to position")
    render_apply_assistance_panel(base_dir, job)


def render_apply_assistance_panel(base_dir: Path, job: JobListing) -> None:
    """Render the first apply-assistance action for a reviewed job workspace."""

    st.markdown("**Apply Assistance**")
    requirements = load_application_requirements(base_dir, job.id)
    package = load_application_package(base_dir, job.id)
    fill_plan = load_application_fill_plan(base_dir, job.id)
    browser_use_log_dir = Path(base_dir) / RUNTIME_DATA_DIR / "browser_use"
    blockers = get_apply_assistance_blockers(job, requirements, package, fill_plan)

    if blockers:
        st.warning("Apply assistance is blocked until these review steps are complete:")
        for blocker in blockers:
            st.write(f"- {blocker}")

    active_session = get_active_browser_use_session(browser_use_log_dir)
    render_browser_use_process_controls(browser_use_log_dir, job, active_session)

    st.caption(
        "This action opens the reviewed apply URL and asks Browser Use to execute "
        "the reviewed application fill plan."
    )
    if st.button(
        "Apply to job with AI",
        disabled=bool(blockers),
        type="primary",
        help=AI_ACTION_COST_HELP,
    ):
        if blockers:
            st.error("Complete the required review steps before opening the apply flow.")
            return
        if fill_plan is None:
            st.error("Generate and review the application fill plan before applying.")
            return
        try:
            with st.spinner("Starting Browser Use apply agent..."):
                result = open_apply_url_with_browser_use_fill_plan(
                    str(job.apply_url),
                    fill_plan=fill_plan,
                    log_dir=browser_use_log_dir,
                )
        except BrowserUseLaunchError as exc:
            st.error(str(exc))
            return

        st.success(f"Started Browser Use apply agent for {result.url}.")
        st.caption(f"Process ID: {result.pid}. Log: {result.log_path}")


def render_browser_use_process_controls(
    browser_use_log_dir: Path,
    job: JobListing,
    active_session: object,
) -> None:
    """Render Browser Use process controls without dominating the apply panel."""

    with st.expander("Browser process controls", expanded=False):
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


def render_application_fill_plan_panel(base_dir: Path, job: JobListing) -> None:
    """Render fill-plan generation, review, and edit controls."""

    st.subheader("Application Fill Plan")
    candidate_profile = load_candidate_profile(base_dir)
    requirements = load_application_requirements(base_dir, job.id)
    page_snapshot = load_application_page_snapshot(base_dir, job.id)
    package = load_application_package(base_dir, job.id)
    fill_plan = load_application_fill_plan(base_dir, job.id)

    generation_blockers = get_fill_plan_generation_blockers(requirements, package)
    if generation_blockers:
        st.warning("Fill plan generation is blocked until these steps are complete:")
        for blocker in generation_blockers:
            st.write(f"- {blocker}")

    if st.button(
        "Generate or refresh fill plan with AI",
        disabled=bool(generation_blockers),
        type="primary",
        help=AI_ACTION_COST_HELP,
    ):
        if requirements is None or package is None:
            st.error("Complete fill plan prerequisites before generating.")
            return
        try:
            with st.spinner("Mapping application fields to candidate evidence..."):
                fill_plan = generate_application_fill_plan(
                    candidate_profile,
                    requirements,
                    package,
                    page_snapshot=page_snapshot,
                    semantic_mapper=map_application_fields_with_llm,
                )
                saved_path = save_application_fill_plan(base_dir, fill_plan)
        except RuntimeError as exc:
            st.error(str(exc))
            return
        st.success(f"Application fill plan saved to {saved_path}.")
        st.rerun()

    if fill_plan is None:
        st.info("No application fill plan has been generated yet.")
        return

    fill_plan = render_application_fill_plan_edit_actions(base_dir, fill_plan)
    review_blockers = get_application_fill_plan_review_blockers(fill_plan)
    if fill_plan.review_status != "reviewed":
        if review_blockers:
            st.warning("Resolve all fill-plan review blockers before marking the plan reviewed.")
        if st.button("Mark Fill Plan Reviewed", disabled=bool(review_blockers)):
            try:
                reviewed_fill_plan = mark_application_fill_plan_reviewed(fill_plan)
            except ValueError as exc:
                st.error(str(exc))
                return
            save_application_fill_plan(base_dir, reviewed_fill_plan)
            st.success("Application fill plan was marked as reviewed.")
            st.rerun()


def get_fill_plan_generation_blockers(
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
) -> list[str]:
    """Return blockers that prevent generating an application fill plan."""

    blockers: list[str] = []
    if requirements is None:
        blockers.append("Discover application requirements.")
    elif requirements.status != "discovered" or not requirements.job_preserving:
        blockers.append("Resolve reviewed application requirements.")
    elif requirements.review_status != "reviewed":
        blockers.append("Review the discovered application requirements.")

    if package is None:
        blockers.append("Generate the application package.")
    elif package.status == "rejected":
        blockers.append("Regenerate or manually edit the rejected application package.")

    return blockers


def render_application_fill_plan_edit_actions(
    base_dir: Path,
    fill_plan: ApplicationFillPlan,
) -> ApplicationFillPlan:
    """Render fill-plan edit controls and return the current fill plan."""

    if (
        not fill_plan.field_values
        and not fill_plan.upload_files
        and not fill_plan.needs_answer_fields
        and not fill_plan.blocked_fields
    ):
        return fill_plan

    with st.form(f"application_fill_plan_edit_form_{fill_plan.job_id}"):
        st.caption(
            "Prefilled values are ready to save. Edit only the fields that need "
            "a correction before Browser Use receives them."
        )
        edited_values: dict[str, str] = {}
        needs_answer_values_by_key: dict[str, str] = {}
        blocked_values_by_key: dict[str, str] = {}

        required_existing_fields = [
            ("field", index, field)
            for index, field in enumerate(fill_plan.field_values)
            if field.required
        ]
        required_needs_answer_fields = [
            ("needs", index, field)
            for index, field in enumerate(fill_plan.needs_answer_fields)
            if field.required
        ]
        required_blocked_fields = [
            ("blocked", index, field)
            for index, field in enumerate(fill_plan.blocked_fields)
            if field.required
        ]
        optional_existing_fields = [
            ("field", index, field)
            for index, field in enumerate(fill_plan.field_values)
            if not field.required
        ]
        optional_needs_answer_fields = [
            ("needs", index, field)
            for index, field in enumerate(fill_plan.needs_answer_fields)
            if not field.required
        ]
        optional_blocked_fields = [
            ("blocked", index, field)
            for index, field in enumerate(fill_plan.blocked_fields)
            if not field.required
        ]

        required_rows = [
            *required_existing_fields,
            *required_needs_answer_fields,
            *required_blocked_fields,
        ]
        optional_rows = [
            *optional_existing_fields,
            *optional_needs_answer_fields,
            *optional_blocked_fields,
        ]

        with st.container(border=True):
            st.markdown("**Required fields**")
            if not required_rows:
                st.caption("No required fields.")
            for kind, index, field in required_rows:
                edit_key = _fill_plan_row_edit_key(kind, field, index)
                value_key = f"application_fill_plan_{fill_plan.job_id}_{edit_key}"
                edited_value = _render_fill_plan_value_input(
                    field,
                    key=value_key,
                    value=_fill_plan_row_default_value(kind, field),
                )
                _record_fill_plan_row_value(
                    kind,
                    edit_key,
                    edited_value,
                    edited_values,
                    needs_answer_values_by_key,
                    blocked_values_by_key,
                )
                _render_fill_plan_edit_reason(field)

        upload_paths_by_key: dict[str, str] = {}
        with st.container(border=True):
            st.markdown("**Uploads Sent To Browser**")
            if not fill_plan.upload_files:
                st.caption("No uploads sent to browser.")
            for index, upload in enumerate(fill_plan.upload_files):
                edit_key = fill_plan_upload_edit_key(upload, index)
                path_key = f"application_fill_plan_upload_path_{fill_plan.job_id}_{edit_key}"
                upload_paths_by_key[edit_key] = st.text_input(
                    f"{upload.label} file path",
                    value=upload.file_path,
                    key=path_key,
                )

        with st.expander("Optional or unclear", expanded=False):
            if not optional_rows:
                st.caption("No optional or unclear fields.")
            for kind, index, field in optional_rows:
                edit_key = _fill_plan_row_edit_key(kind, field, index)
                value_key = f"application_fill_plan_{fill_plan.job_id}_{edit_key}"
                edited_value = _render_fill_plan_value_input(
                    field,
                    key=value_key,
                    value=_fill_plan_row_default_value(kind, field),
                )
                _record_fill_plan_row_value(
                    kind,
                    edit_key,
                    edited_value,
                    edited_values,
                    needs_answer_values_by_key,
                    blocked_values_by_key,
                )
                _render_fill_plan_edit_reason(field)

        save_edits = st.form_submit_button("Save Fill Plan Edits", type="primary")

    if not save_edits:
        return fill_plan

    edited_fill_plan = apply_fill_plan_edits(
        fill_plan,
        edited_values,
        upload_paths_by_key=upload_paths_by_key,
        needs_answer_values_by_key=needs_answer_values_by_key,
        blocked_values_by_key=blocked_values_by_key,
    )
    save_application_fill_plan(base_dir, edited_fill_plan)
    st.success("Fill plan edits saved. Review status reset to draft.")
    st.rerun()
    return edited_fill_plan


def _fill_plan_row_edit_key(
    kind: str,
    field: (
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField
    ),
    index: int,
) -> str:
    if kind == "field":
        return fill_plan_field_edit_key(field, index)
    if kind == "needs":
        return fill_plan_needs_answer_edit_key(field, index)
    return fill_plan_blocked_field_edit_key(field, index)


def _fill_plan_row_default_value(
    kind: str,
    field: (
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField
    ),
) -> str:
    if kind == "field":
        return field.value
    if kind == "blocked":
        return _default_blocked_field_review_value(field)
    return ""


def _default_blocked_field_review_value(field: ApplicationFillBlockedField) -> str:
    input_type = field.input_type.casefold()
    if input_type == "checkbox":
        return "true" if field.required else "false"
    return ""


def _render_fill_plan_value_input(
    field: (
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField
    ),
    *,
    key: str,
    value: str,
) -> str:
    input_type = field.input_type.casefold()
    options = list(field.options)

    if input_type == "checkbox":
        checked = value.strip().casefold() in {"true", "yes", "ja", "1", "checked"}
        return "true" if st.checkbox(field.label, value=checked, key=key) else "false"

    if input_type in {"checkbox_group", "multiselect", "multi_select"} and options:
        selected = st.multiselect(
            field.label,
            options=options,
            default=_selected_fill_plan_options(value, options),
            key=key,
        )
        return "; ".join(selected)

    if input_type in {"select", "radio"} and options:
        selectable_options = _selectable_fill_plan_options(value, options)
        selected = st.selectbox(
            field.label,
            options=selectable_options,
            index=selectable_options.index(value) if value in selectable_options else 0,
            key=key,
        )
        return selected

    return st.text_input(field.label, value=value, key=key)


def _selected_fill_plan_options(value: str, options: list[str]) -> list[str]:
    reviewed_value = value.strip()
    if not reviewed_value:
        return []
    if ";" in reviewed_value:
        selected = [part.strip() for part in reviewed_value.split(";") if part.strip()]
        return [option for option in options if option in selected]
    if reviewed_value in options:
        return [reviewed_value]
    return []


def _selectable_fill_plan_options(value: str, options: list[str]) -> list[str]:
    reviewed_value = value.strip()
    selectable_options = ["", *options]
    if reviewed_value and reviewed_value not in selectable_options:
        selectable_options.append(reviewed_value)
    return selectable_options


def _record_fill_plan_row_value(
    kind: str,
    edit_key: str,
    value: str,
    edited_values: dict[str, str],
    needs_answer_values_by_key: dict[str, str],
    blocked_values_by_key: dict[str, str],
) -> None:
    if kind == "field":
        edited_values[edit_key] = value
        return
    if kind == "needs":
        needs_answer_values_by_key[edit_key] = value
        return
    blocked_values_by_key[edit_key] = value


def _render_fill_plan_edit_reason(
    field: (
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField
    ),
) -> None:
    reason = getattr(field, "reason", "").strip()
    if reason:
        st.caption(reason)


def render_application_package_review_form(
    base_dir: Path,
    job: JobListing,
    package: ApplicationPackage,
) -> ApplicationPackage:
    """Render package review fields and return the current package state."""

    render_application_package_summary(package)

    with st.form(f"application_package_review_form_{job.id}"):
        edited_content: dict[str, str] = {}
        for artifact in order_application_package_artifacts_for_review(package.artifacts):
            with st.expander(
                artifact.label,
                expanded=is_cover_letter_artifact(artifact),
            ):
                render_application_artifact_review_metadata(artifact)
                edited_content[artifact.id] = st.text_area(
                    f"{artifact.label} content",
                    value=artifact.content,
                    key=application_artifact_review_key(job.id, artifact),
                )
                render_artifact_traceability(artifact.metadata)

        save_edits = st.form_submit_button(
            "Save package review changes",
            type="primary",
        )

    current_package = package
    if save_edits:
        if not application_package_review_has_content_changes(package, edited_content):
            st.info("No package review changes were made.")
        else:
            current_package = apply_application_package_review_edits(package, edited_content)
            json_path, markdown_path = save_application_package(base_dir, current_package, job)
            update_tracker_for_application_package(base_dir, job.id, json_path)
            st.success(
                build_package_review_saved_message(
                    json_path,
                    markdown_path,
                    current_package,
                )
            )

    render_cover_letter_artifact_export_controls(base_dir, job, current_package)
    return current_package


def render_cover_letter_artifact_export_controls(
    base_dir: Path,
    job: JobListing,
    package: ApplicationPackage,
) -> None:
    """Render a user-selected folder export action for the cover letter artifact."""

    cover_letter = find_cover_letter_artifact(package)
    if cover_letter is None or not cover_letter.content.strip():
        return

    default_destination = application_package_artifacts_dir(base_dir, job.id)
    st.markdown("**Cover Letter Artifact**")
    destination_text = st.text_input(
        "Cover letter destination folder",
        value=str(default_destination),
        key=f"cover_letter_artifact_destination_{job.id}",
    )
    if not st.button("Export cover letter PDF", key=f"export_cover_letter_artifact_{job.id}"):
        return

    if not destination_text.strip():
        st.error("Choose a destination folder before exporting the cover letter.")
        return
    destination = Path(destination_text).expanduser()

    try:
        exported_path = export_cover_letter_artifact(package, destination)
        json_path, markdown_path = save_application_package(base_dir, package, job)
        update_tracker_for_application_package(base_dir, job.id, json_path)
    except OSError as exc:
        st.error(f"Could not export cover letter artifact: {exc}")
        return

    if exported_path is None:
        st.warning("No cover letter artifact is available to export.")
        return
    st.success(
        "Cover letter PDF exported.\n\n"
        f"- Downloaded artifact: {exported_path}\n"
        f"- Package JSON updated: {json_path}\n"
        f"- Markdown export updated: {markdown_path}"
    )


def find_cover_letter_artifact(package: ApplicationPackage) -> ApplicationArtifact | None:
    """Return the first cover-letter artifact in a package."""

    for artifact in package.artifacts:
        if is_cover_letter_artifact(artifact):
            return artifact
    return None


def build_package_review_saved_message(
    json_path: Path,
    markdown_path: Path,
    package: ApplicationPackage,
) -> str:
    """Return a save confirmation that names package exports and locations."""

    lines = [
        "Package review changes saved.",
        f"- Package JSON: {json_path}",
        f"- Markdown export: {markdown_path}",
    ]
    cover_letter = find_cover_letter_artifact(package)
    if cover_letter is not None:
        generated_path = str(cover_letter.metadata.get("generated_file_path") or "").strip()
        if generated_path:
            lines.append(f"- Cover letter PDF artifact: {generated_path}")
    return "\n".join(lines)


def render_application_package_summary(package: ApplicationPackage) -> None:
    """Render compact generated package status before editable review fields."""

    summary = build_application_package_summary(package)
    selected_experience_units = summary["selected_experience_units"]
    if isinstance(selected_experience_units, list) and selected_experience_units:
        st.markdown("**Selected Experience Units**")
        for item in selected_experience_units:
            st.write(f"- {item}")


def build_application_package_summary(
    package: ApplicationPackage,
) -> dict[str, str | int | list[str]]:
    """Return compact package metadata for the package review form."""

    return {
        "status": package.status,
        "artifact_count": len(package.artifacts),
        "missing_information": list(package.missing_information),
        "selected_experience_units": list(package.selected_experience_units),
        "generation_notes": list(package.generation_notes),
    }


def render_application_artifact_review_metadata(artifact: ApplicationArtifact) -> None:
    """Render artifact metadata next to its editable content field."""

    for item in build_application_artifact_review_metadata(artifact):
        st.caption(item)


def build_application_artifact_review_metadata(
    artifact: ApplicationArtifact,
) -> list[str]:
    """Return reviewer-facing metadata labels for an application artifact."""

    metadata = []
    if artifact.source_prompt:
        metadata.append(f"Source prompt: {artifact.source_prompt}")
    if artifact.source_requirement:
        metadata.append(f"Source requirement: {artifact.source_requirement}")
    return metadata


def application_artifact_review_key(job_id: str, artifact: ApplicationArtifact) -> str:
    """Return a Streamlit widget key tied to the current artifact content."""

    content_hash = hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()[:12]
    return f"application_package_review_{job_id}_{artifact.id}_{content_hash}"


def order_application_package_artifacts_for_review(
    artifacts: list[ApplicationArtifact],
) -> list[ApplicationArtifact]:
    """Return artifacts with the cover letter first while preserving other order."""

    return sorted(
        artifacts,
        key=lambda artifact: 0 if is_cover_letter_artifact(artifact) else 1,
    )


def is_cover_letter_artifact(artifact: ApplicationArtifact) -> bool:
    """Return whether an artifact is the cover-letter draft."""

    normalized_label = artifact.label.casefold()
    return artifact.type == "cover_letter" or "cover letter" in normalized_label


def application_package_review_has_content_changes(
    package: ApplicationPackage,
    edits_by_artifact_id: dict[str, str],
) -> bool:
    """Return whether reviewer edits change any stored artifact content."""

    for artifact in package.artifacts:
        if artifact.id not in edits_by_artifact_id:
            continue
        if str(edits_by_artifact_id[artifact.id]).strip() != artifact.content:
            return True
    return False


def apply_application_package_review_edits(
    package: ApplicationPackage,
    edits_by_artifact_id: dict[str, str],
) -> ApplicationPackage:
    """Apply reviewer edits and unlock legacy rejected packages when changed."""

    edited_package = apply_manual_artifact_edits(package, edits_by_artifact_id)
    if (
        package.status == "rejected"
        and application_package_review_has_content_changes(package, edits_by_artifact_id)
    ):
        edited_package.status = "manually_edited"
    return edited_package


def render_application_requirements(requirements: ApplicationRequirements) -> None:
    """Render interpreted application requirements with compact defaults."""

    if requirements.blocked_reason:
        st.warning(requirements.blocked_reason)

    render_application_requirements_compact(requirements)

    with st.expander("Requirements evidence and form details", expanded=False):
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
            st.markdown("**Source Evidence**")
            for evidence in requirements.source_evidence:
                st.write(f"- {evidence}")


def render_application_requirements_compact(requirements: ApplicationRequirements) -> None:
    """Render the application requirements that matter most at a glance."""

    key_items: list[str] = []
    key_items.extend(finding.label for finding in requirements.required_documents)
    key_items.extend(finding.label for finding in requirements.upload_expectations)
    if requirements.motivation_letter:
        key_items.append(requirements.motivation_letter.label)
    key_items.extend(
        finding.label for finding in requirements.consent_requirements if finding.required
    )

    if key_items:
        st.markdown("**Key Requirements**")
        for item in deduplicate_review_items(key_items):
            st.write(f"- {item}")


def get_apply_assistance_blockers(
    job: JobListing,
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
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

    if fill_plan is None:
        blockers.append("Generate the application fill plan before applying.")
    else:
        fill_plan_review_blockers = get_application_fill_plan_review_blockers(fill_plan)
        if fill_plan_review_blockers:
            blockers.extend(fill_plan_review_blockers)
        elif fill_plan.review_status != "reviewed":
            blockers.append("Review the application fill plan before applying.")

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
