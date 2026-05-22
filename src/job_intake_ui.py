"""Streamlit UI helpers for the URL-first job intake workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.app_workflow import (
    apply_resolution_details,
    apply_url_review_messages,
    extract_job_intake_data,
    lines_from_text,
    resolved_apply_url,
    validate_reviewed_apply_url,
    workflow_trace_payload,
)
from src.job_intake import create_job_listing, persist_job_listing
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData
from src.schemas import JobListing
from src.ui_components import AI_ACTION_COST_HELP, render_optional_ai_details


@dataclass(frozen=True)
class JobReviewFormState:
    """Submitted state from the reviewed job-intake form."""

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


def render_job_url_extraction_form() -> tuple[bool, str]:
    """Render the initial job URL extraction form."""

    with st.form("job_url_form"):
        source_url = st.text_input("Job URL", placeholder="https://company.com/jobs/role")
        st.caption("Extract uses AI to resolve application data.")
        extract_submitted = st.form_submit_button(
            "Extract application data with AI",
            type="primary",
            help=AI_ACTION_COST_HELP,
        )
    return extract_submitted, source_url


def handle_job_url_extraction(source_url: str) -> bool:
    """Run job extraction and store review payloads in Streamlit session state."""

    try:
        with st.spinner("Extracting job data with AI..."):
            extraction_result = extract_job_intake_data(source_url)
    except (RuntimeError, ValueError) as exc:
        st.error(str(exc))
        return False

    st.session_state["job_intake_source_url"] = source_url.strip()
    st.session_state["job_intake_extracted"] = extraction_result.extracted.model_dump(mode="json")
    st.session_state["job_intake_apply_resolution"] = (
        extraction_result.apply_resolution.model_dump(mode="json")
    )
    return True


def load_job_intake_review_state() -> (
    tuple[ExtractedJobData, ApplyUrlResolution | None, str] | None
):
    """Load pending job-intake review state from Streamlit session state."""

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
    """Render job-intake header and return the verified apply URL."""

    st.subheader("Review Extracted Data")
    st.caption("Review what the AI found before adding it to the application workflow.")

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
    """Render the reviewed job-intake form and return submitted values."""

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
    """Build a persistable job listing from reviewed form state."""

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
    """Clear pending job-intake review data from Streamlit session state."""

    st.session_state.pop("job_intake_source_url", None)
    st.session_state.pop("job_intake_extracted", None)
    st.session_state.pop("job_intake_apply_resolution", None)


def render_job_intake_page(base_dir: Path) -> None:
    """Render the URL-first job intake workflow."""

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
    render_optional_ai_details(
        "job intake review",
        [
            ("Job Extraction Trace", extracted_data.workflow_trace),
            (
                "Apply URL Resolution Trace",
                apply_resolution.workflow_trace if apply_resolution else None,
            ),
        ],
        summary_label="Job Intake AI Usage Summary",
        summary_traces=[
            extracted_data.workflow_trace,
            apply_resolution.workflow_trace if apply_resolution else None,
        ],
    )

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
