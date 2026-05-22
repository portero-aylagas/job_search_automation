"""Streamlit UI for candidate profile intake and review."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.app_workflow import (
    lines_from_text,
    load_candidate_profile,
    save_candidate_profile,
)
from src.candidate_profile import (
    is_valid_email,
    merge_supplemental_extracted_data,
    validate_candidate_profile,
)
from src.cv_extraction import (
    run_cv_extraction_task,
    run_optional_document_extraction_task,
    save_uploaded_cv,
    save_uploaded_optional_document,
)
from src.schemas import CandidateOptionalDocument, CandidateProfile
from src.ui_components import AI_ACTION_COST_HELP, render_optional_ai_details

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
GENDER_OPTIONS = ["Male", "Female", "Diverse"]
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
TEXTAREA_PIXELS_PER_ROW = 26
TEXTAREA_VERTICAL_PADDING = 24
TEXTAREA_WRAP_CHARS = 92


def get_candidate_profile_draft(base_dir: Path) -> dict:
    """Load or initialize the candidate profile draft in Streamlit session state."""

    draft = st.session_state.get("candidate_profile_draft")
    if draft is None:
        draft = load_candidate_profile(base_dir).model_dump(mode="json")
        st.session_state["candidate_profile_draft"] = draft
    return draft


def set_candidate_profile_draft(draft: dict) -> None:
    """Replace the candidate profile draft stored in Streamlit session state."""

    st.session_state["candidate_profile_draft"] = draft


def required_label(label: str) -> str:
    """Return a UI label marked as required."""

    return f"{label} *"


def work_authorization_index(value: str) -> int | None:
    """Return the radio index for the saved work authorization value."""

    for index, (option_value, _) in enumerate(WORK_AUTHORIZATION_OPTIONS):
        if option_value == value:
            return index
    return None


def gender_index(value: str | None) -> int | None:
    """Return the select index for the saved gender value."""

    if value in GENDER_OPTIONS:
        return GENDER_OPTIONS.index(value)
    return None


def review_text_from_items(items: list[str]) -> str:
    """Return extracted CV items as a readable editable bullet list."""

    return "\n".join(f"- {item.strip()}" for item in items if item.strip())


def review_block_text_from_items(items: list[str]) -> str:
    """Return extracted CV items as editable title-and-bullet blocks."""

    blocks: list[str] = []
    for item in items:
        lines = [line.strip("-*• \t") for line in item.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            blocks.append(lines[0])
            continue
        title = lines[0]
        bullets = "\n".join(f"- {line}" for line in lines[1:])
        blocks.append(f"{title}\n{bullets}")
    return "\n\n".join(blocks)


def review_blocks_from_text(value: str) -> list[str]:
    """Parse editable title-and-bullet blocks into stored CV items."""

    items: list[str] = []
    for raw_block in value.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        lines = [line.strip("-*• \t") for line in raw_block.splitlines() if line.strip()]
        if lines:
            items.append("\n".join(lines))
    return items


def adaptive_text_area_height(
    value: str,
    *,
    min_rows: int,
    max_rows: int = 24,
    wrap_chars: int = TEXTAREA_WRAP_CHARS,
) -> int:
    """Estimate a Streamlit text area height from visible review text."""

    visible_lines = value.splitlines() or [""]
    wrapped_rows = sum(
        max(1, (len(line) + wrap_chars - 1) // wrap_chars)
        for line in visible_lines
    )
    rows = min(max_rows, max(min_rows, wrapped_rows + 1))
    return rows * TEXTAREA_PIXELS_PER_ROW + TEXTAREA_VERTICAL_PADDING


def render_candidate_profile_page(base_dir: Path) -> None:
    """Render the candidate profile workflow page."""

    st.title("Candidate Profile")
    st.write(
        "Upload your CV and certifications once, review the extracted data, and "
        "fill in the missing job-search preferences."
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
    """Render CV upload controls and update draft data after parsing."""

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

        if st.button("Parse CV with AI", type="primary", help=AI_ACTION_COST_HELP):
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
    """Return the user-facing error shown when CV parsing fails after upload."""

    return (
        f"CV upload was saved to {saved_path}, but AI parsing failed: {exc}. "
        "Check that the Streamlit process has OPENAI_API_KEY and network access, "
        "then click Parse CV with AI again."
    )


def render_optional_documents_section(base_dir: Path, candidate_profile: CandidateProfile) -> None:
    """Render optional document upload controls and merge parsed evidence."""

    with st.container(border=True):
        st.subheader("2. Optional documents")

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

        if st.button(
            "Parse optional documents with AI",
            type="primary",
            help=AI_ACTION_COST_HELP,
        ):
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
            with st.spinner("Parsing optional documents with the AI extractor..."):
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
    """Render editable CV-extracted fields and save changes into the draft."""

    with st.container(border=True):
        st.subheader("3. Extracted data review")
        profile_data = candidate_profile.candidate_profile
        extracted = profile_data.cv_extracted

        if not profile_data.source_documents.cv.parsed:
            st.info("Upload and parse a CV to populate these review fields.")

        with st.form("candidate_profile_review_form"):
            st.markdown("**Identity**")
            identity_left, identity_right = st.columns(2)
            with identity_left:
                first_name = st.text_input(
                    required_label("First name"),
                    value=extracted.identity.first_name,
                )
                last_name = st.text_input(
                    required_label("Surname"),
                    value=extracted.identity.last_name,
                )
                gender = st.selectbox(
                    required_label("Gender"),
                    options=GENDER_OPTIONS,
                    index=gender_index(extracted.identity.gender),
                    placeholder="Select gender",
                )
                email = st.text_input(required_label("Email"), value=extracted.identity.email)
                phone = st.text_input(required_label("Phone"), value=extracted.identity.phone)
                location = st.text_input("Location", value=extracted.identity.location)
            with identity_right:
                street_address = st.text_input(
                    required_label("Street"),
                    value=extracted.identity.street_address,
                )
                street_number = st.text_input(
                    required_label("Street number"),
                    value=extracted.identity.street_number,
                )
                postal_code = st.text_input(
                    required_label("Postal code"),
                    value=extracted.identity.postal_code,
                )
                city = st.text_input(required_label("City"), value=extracted.identity.city)
                country = st.text_input(
                    required_label("Country of residence"),
                    value=extracted.identity.country,
                )
                nationality = st.text_input(
                    required_label("Nationality"),
                    value=extracted.identity.nationality,
                )
                linkedin_url = st.text_input(
                    "LinkedIn URL", value=extracted.identity.linkedin_url
                )
                github_url = st.text_input("GitHub URL", value=extracted.identity.github_url)
                portfolio_url = st.text_input(
                    "Portfolio URL", value=extracted.identity.portfolio_url
                )

            st.markdown("**Professional data**")
            work_experience_text = review_block_text_from_items(extracted.work_experience)
            work_experience = st.text_area(
                "Work experience",
                value=work_experience_text,
                height=adaptive_text_area_height(
                    work_experience_text,
                    min_rows=4,
                    max_rows=18,
                ),
            )
            education_text = review_text_from_items(extracted.education)
            education = st.text_area(
                "Education",
                value=education_text,
                height=adaptive_text_area_height(education_text, min_rows=4, max_rows=18),
            )
            skills_text = review_text_from_items(extracted.skills)
            skills = st.text_area(
                "Skills",
                value=skills_text,
                height=adaptive_text_area_height(
                    skills_text,
                    min_rows=7,
                    max_rows=24,
                    wrap_chars=70,
                ),
            )
            languages_text = review_text_from_items(extracted.languages)
            languages = st.text_area(
                "Languages",
                value=languages_text,
                height=adaptive_text_area_height(languages_text, min_rows=4, max_rows=14),
            )
            certifications_text = review_text_from_items(extracted.certifications)
            certifications = st.text_area(
                "Certifications",
                value=certifications_text,
                height=adaptive_text_area_height(
                    certifications_text,
                    min_rows=4,
                    max_rows=16,
                ),
            )
            projects_text = review_text_from_items(extracted.projects)
            projects = st.text_area(
                "Projects",
                value=projects_text,
                height=adaptive_text_area_height(projects_text, min_rows=5, max_rows=18),
            )
            references_text = review_text_from_items(extracted.references)
            references = st.text_area(
                "References",
                value=references_text,
                height=adaptive_text_area_height(references_text, min_rows=4, max_rows=16),
            )

            save_extracted = st.form_submit_button(
                "Save CV review changes",
                type="primary",
            )

        render_optional_ai_details(
            "CV review",
            [("CV Extraction Trace", extracted.workflow_trace)],
            summary_label="CV AI Usage Summary",
            summary_traces=[extracted.workflow_trace],
        )

        if not save_extracted:
            return

        normalized_email = email.strip().lower()
        if normalized_email and not is_valid_email(normalized_email):
            st.error("Email must be a valid address before saving CV review changes.")
            return

        updated_profile = candidate_profile.model_copy(deep=True)
        updated_profile.candidate_profile.cv_extracted.identity.first_name = first_name.strip()
        updated_profile.candidate_profile.cv_extracted.identity.last_name = last_name.strip()
        updated_profile.candidate_profile.cv_extracted.identity.full_name = " ".join(
            item for item in (first_name.strip(), last_name.strip()) if item
        )
        updated_profile.candidate_profile.cv_extracted.identity.gender = gender
        updated_profile.candidate_profile.cv_extracted.identity.email = normalized_email
        updated_profile.candidate_profile.cv_extracted.identity.phone = phone.strip()
        updated_profile.candidate_profile.cv_extracted.identity.location = location.strip()
        updated_profile.candidate_profile.cv_extracted.identity.street_address = (
            street_address.strip()
        )
        updated_profile.candidate_profile.cv_extracted.identity.street_number = (
            street_number.strip()
        )
        updated_profile.candidate_profile.cv_extracted.identity.postal_code = (
            postal_code.strip()
        )
        updated_profile.candidate_profile.cv_extracted.identity.city = city.strip()
        updated_profile.candidate_profile.cv_extracted.identity.country = country.strip()
        updated_profile.candidate_profile.cv_extracted.identity.nationality = (
            nationality.strip()
        )
        updated_profile.candidate_profile.cv_extracted.identity.linkedin_url = linkedin_url.strip()
        updated_profile.candidate_profile.cv_extracted.identity.github_url = github_url.strip()
        updated_profile.candidate_profile.cv_extracted.identity.portfolio_url = (
            portfolio_url.strip()
        )
        updated_profile.candidate_profile.cv_extracted.work_experience = review_blocks_from_text(
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
        updated_profile = CandidateProfile.model_validate(
            updated_profile.model_dump(mode="json")
        )
        set_candidate_profile_draft(updated_profile.model_dump(mode="json"))
        st.success("CV review fields updated.")
        st.rerun()


def render_candidate_preferences_section(candidate_profile: CandidateProfile) -> None:
    """Render manual candidate preference inputs and update the draft."""

    with st.container(border=True):
        st.subheader("4. Manual candidate preferences")
        profile_data = candidate_profile.candidate_profile
        preferences = profile_data.candidate_preferences

        with st.form("candidate_profile_preferences_form"):
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

            availability = st.text_input(
                required_label("Availability"),
                value=preferences.availability,
            )
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
            save_preferences = st.form_submit_button(
                "Save manual preferences",
                type="primary",
            )

        if not save_preferences:
            return

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
        st.success("Manual preferences updated.")


def get_latest_candidate_profile(base_dir: Path) -> CandidateProfile:
    """Return the current candidate profile draft as a validated model."""

    return CandidateProfile.model_validate(get_candidate_profile_draft(base_dir))


def render_profile_save_section(base_dir: Path, _candidate_profile: CandidateProfile) -> None:
    """Render the profile save action and persist a valid reviewed profile."""

    st.subheader("Save")
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
