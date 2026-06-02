"""FastAPI adapter for the reviewed job application workflow."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from src.agent_chat import ACTION_LABELS, load_agent_chat_messages
from src.agent_workflow import run_agent_workflow
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.tools import build_karen_context
from src.app_workflow import (
    apply_resolution_details,
    apply_url_review_messages,
    extract_job_intake_data,
    get_application_package_blockers,
    lines_from_text,
    load_app_data,
    load_application_page_snapshot,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_jobs_index,
    load_normalized_job,
    resolved_apply_url,
    save_candidate_profile,
    validate_reviewed_apply_url,
    workflow_trace_payload,
)
from src.application_fill_plan import (
    apply_fill_plan_edits,
    fill_plan_blocked_field_edit_key,
    fill_plan_field_edit_key,
    fill_plan_needs_answer_edit_key,
    fill_plan_upload_edit_key,
    generate_application_fill_plan,
    load_application_fill_plan,
    map_application_fields_with_llm,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.application_package import (
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
    count_browser_use_runner_processes,
    get_active_browser_use_session,
    open_apply_url_with_browser_use_fill_plan,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.candidate_profile import (
    is_valid_email,
    merge_supplemental_extracted_data,
    normalize_candidate_profile_documents,
    validate_candidate_profile,
)
from src.cv_extraction import (
    run_cv_extraction_task,
    run_optional_document_extraction_task,
    save_uploaded_cv,
    save_uploaded_optional_document,
)
from src.job_intake import create_job_listing, persist_job_listing
from src.job_workspace import (
    apply_application_package_review_edits,
    apply_application_requirements_review_edits,
    build_application_package_summary,
    get_apply_assistance_blockers,
    get_fill_plan_generation_blockers,
    mark_application_package_reviewed,
)
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData
from src.paths import RUNTIME_DATA_DIR
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateOptionalDocument,
    CandidateProfile,
)
from src.tracker_status import (
    tracker_status_filters,
    tracker_status_options,
    update_manual_tracker_status,
    update_tracker_record,
)

PAGE_NAMES = ["Candidate Profile", "Job Intake", "Jobs", "Tracker", "Agent Karen"]
BASE_DIR = Path(__file__).resolve().parent.parent
API_BROWSER_USE_STARTUP_WAIT_SECONDS = 0.0


class FilePayload(BaseModel):
    """Browser-uploaded file encoded for JSON transport."""

    filename: str
    content_base64: str
    document_type: str = "other"


class CandidateProfilePayload(BaseModel):
    """Candidate profile payload edited by the React UI."""

    profile: CandidateProfile


class JobExtractionRequest(BaseModel):
    """Job URL extraction request."""

    source_url: str


class JobReviewRequest(BaseModel):
    """Reviewed job-intake fields from the URL-first form."""

    source_url: str
    extracted_data: ExtractedJobData
    apply_resolution: ApplyUrlResolution | None = None
    title: str
    company: str
    location: str = ""
    remote_policy: str = ""
    apply_url: str = ""
    salary: str = ""
    posted_date: str = ""
    source_job_id: str = ""
    description: str = ""
    requirements: str = ""
    responsibilities: str = ""
    nice_to_have_skills: str = ""
    dynamic_fields: list[dict[str, object]] = Field(default_factory=list)


class RequirementsReviewRequest(BaseModel):
    """Editable application requirements review fields."""

    job_preserving: bool
    confidence: str
    blocked_reason: str = ""
    required_documents_text: str = ""
    upload_expectations_text: str = ""
    motivation_label: str = ""
    motivation_required: bool = False
    profile_fields_text: str = ""
    screening_questions_text: str = ""
    custom_form_fields_text: str = ""
    consent_requirements_text: str = ""
    privacy_login_ats_gates_text: str = ""
    deadlines_text: str = ""
    contact_or_fallback_text: str = ""
    missing_or_uncertain_text: str = ""


class PackageReviewRequest(BaseModel):
    """Editable package artifact content keyed by artifact ID."""

    edits_by_artifact_id: dict[str, str]


class CoverLetterExportRequest(BaseModel):
    """Cover-letter export destination."""

    destination_folder: str


class FillPlanReviewRequest(BaseModel):
    """Editable fill-plan review values keyed by backend edit keys."""

    edited_values: dict[str, str] = Field(default_factory=dict)
    upload_paths_by_key: dict[str, str] = Field(default_factory=dict)
    needs_answer_values_by_key: dict[str, str] = Field(default_factory=dict)
    blocked_values_by_key: dict[str, str] = Field(default_factory=dict)


class TrackerStatusUpdateRequest(BaseModel):
    """Manual tracker status update request."""

    status: str


class KarenChatRequest(BaseModel):
    """One Karen chat turn from the Agent Karen page."""

    message: str
    selected_job_id: str | None = None
    session_id: str | None = None


def create_app(base_dir: Path | str = BASE_DIR) -> FastAPI:
    """Create the FastAPI app bound to a repository base directory."""

    app = FastAPI(title="Job Search Automation API")
    app.state.base_dir = Path(base_dir)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Return a lightweight readiness response."""

        return {"status": "ok"}

    @app.get("/api/pages")
    async def pages() -> dict[str, list[str]]:
        """Return the top-level navigation pages."""

        return {"pages": PAGE_NAMES}

    @app.get("/api/candidate-profile")
    async def get_candidate_profile() -> dict[str, object]:
        """Return the current candidate profile and form constants."""

        profile = load_candidate_profile(app.state.base_dir)
        return {"profile": profile.model_dump(mode="json"), "options": candidate_options()}

    @app.put("/api/candidate-profile/review-changes")
    async def save_candidate_review(payload: CandidateProfilePayload) -> dict[str, object]:
        """Persist edited CV review fields as the current candidate draft."""

        profile = normalize_candidate_profile_documents(payload.profile)
        email = profile.candidate_profile.cv_extracted.identity.email
        if email and not is_valid_email(email):
            raise HTTPException(
                status_code=400,
                detail="Email must be a valid address before saving CV review changes.",
            )
        save_candidate_profile(app.state.base_dir, profile)
        return {"profile": profile.model_dump(mode="json"), "message": "CV review fields updated."}

    @app.put("/api/candidate-profile/preferences")
    async def save_candidate_preferences(payload: CandidateProfilePayload) -> dict[str, object]:
        """Persist manual candidate preference edits as the current draft."""

        profile = normalize_candidate_profile_documents(payload.profile)
        save_candidate_profile(app.state.base_dir, profile)
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "Manual preferences updated.",
        }

    @app.post("/api/candidate-profile/save")
    async def save_profile(payload: CandidateProfilePayload) -> dict[str, object]:
        """Validate and save the reviewed candidate profile."""

        profile = normalize_candidate_profile_documents(payload.profile)
        validation_errors = validate_candidate_profile(profile)
        if validation_errors:
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: " + ", ".join(validation_errors),
            )
        saved_path = save_candidate_profile(app.state.base_dir, profile)
        return {"profile": profile.model_dump(mode="json"), "saved_path": str(saved_path)}

    @app.post("/api/candidate-profile/parse-cv")
    async def parse_cv(payload: FilePayload) -> dict[str, object]:
        """Save an uploaded CV and parse it through the existing AI task."""

        content = decode_file_payload(payload)
        saved_path = save_uploaded_cv(app.state.base_dir, payload.filename, content)
        try:
            extracted = run_cv_extraction_task(saved_path)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"CV upload was saved to {saved_path}, but AI parsing failed: {exc}. "
                    "Check that the API process has OPENAI_API_KEY and network access, "
                    "then click Parse CV with AI again."
                ),
            ) from exc

        profile = load_candidate_profile(app.state.base_dir).model_copy(deep=True)
        profile.candidate_profile.source_documents.cv.file_path = str(saved_path)
        profile.candidate_profile.source_documents.cv.parsed = True
        profile.candidate_profile.cv_extracted = extracted
        profile = normalize_candidate_profile_documents(profile)
        save_candidate_profile(app.state.base_dir, profile)
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "CV parsed and loaded into the review form.",
        }

    @app.post("/api/candidate-profile/parse-optional-document")
    async def parse_optional_document(payload: FilePayload) -> dict[str, object]:
        """Save and parse one optional supporting document."""

        content = decode_file_payload(payload)
        saved_path = save_uploaded_optional_document(
            app.state.base_dir,
            payload.filename,
            content,
        )
        profile = load_candidate_profile(app.state.base_dir).model_copy(deep=True)
        document = CandidateOptionalDocument(
            file_path=str(saved_path),
            file_name=payload.filename,
            document_type=payload.document_type,
            parsed=False,
        )
        try:
            extracted = run_optional_document_extraction_task(saved_path)
        except Exception as exc:
            profile.candidate_profile.source_documents.optional_documents.append(document)
            save_candidate_profile(
                app.state.base_dir,
                normalize_candidate_profile_documents(profile),
            )
            raise HTTPException(status_code=500, detail=f"{payload.filename}: {exc}") from exc

        merge_supplemental_extracted_data(profile.candidate_profile.cv_extracted, extracted)
        document.parsed = True
        profile.candidate_profile.source_documents.optional_documents.append(document)
        profile = normalize_candidate_profile_documents(profile)
        save_candidate_profile(app.state.base_dir, profile)
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "Parsed 1 optional document into the review fields.",
        }

    @app.post("/api/job-intake/extract")
    async def extract_job(payload: JobExtractionRequest) -> dict[str, object]:
        """Extract a job URL and resolve its apply URL."""

        try:
            extraction_result = extract_job_intake_data(payload.source_url)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        final_apply_url = resolved_apply_url(
            payload.source_url,
            extraction_result.apply_resolution,
        )
        messages = apply_url_review_messages(
            extraction_result.extracted.apply_url,
            payload.source_url,
            final_apply_url,
        )
        return {
            "source_url": payload.source_url.strip(),
            "extracted_data": extraction_result.extracted.model_dump(mode="json"),
            "apply_resolution": extraction_result.apply_resolution.model_dump(mode="json"),
            "final_apply_url": final_apply_url,
            "apply_url_messages": messages,
        }

    @app.post("/api/job-intake/save")
    async def save_reviewed_job(payload: JobReviewRequest) -> dict[str, object]:
        """Persist reviewed job intake data and update the tracker."""

        try:
            validate_reviewed_apply_url(
                payload.apply_url,
                payload.source_url,
                payload.apply_resolution,
            )
            job = create_job_listing(
                title=payload.title,
                company=payload.company,
                source_url=payload.source_url,
                location=payload.location,
                remote_policy=payload.remote_policy,
                apply_url=payload.apply_url,
                description=payload.description,
                requirements=lines_from_text(payload.requirements),
                responsibilities=lines_from_text(payload.responsibilities),
                nice_to_have_skills=lines_from_text(payload.nice_to_have_skills),
                salary=payload.salary,
                posted_date=payload.posted_date,
                source_job_id=payload.source_job_id,
                job_details={
                    "extraction_confidence": payload.extracted_data.confidence,
                    "job_extraction_trace": workflow_trace_payload(
                        payload.extracted_data.workflow_trace
                    ),
                    "apply_url_resolution": apply_resolution_details(
                        payload.apply_url,
                        payload.source_url,
                        payload.apply_resolution,
                    ),
                    "dynamic_fields": [
                        field
                        for field in payload.dynamic_fields
                        if field.get("name") or field.get("value")
                    ],
                },
            )
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job_path = persist_job_listing(app.state.base_dir, job)
        return {
            "job": job.model_dump(mode="json"),
            "job_path": str(job_path),
            "message": f"Added {job.company} / {job.title} to the workflow.",
        }

    @app.get("/api/tracker")
    async def tracker() -> dict[str, object]:
        """Return tracker records sorted like the Streamlit tracker."""

        _, records = load_app_data(app.state.base_dir)
        sorted_records = sorted(
            records,
            key=lambda record: (record.status, record.company.lower(), record.title.lower()),
        )
        return {
            "records": [record.model_dump(mode="json") for record in sorted_records],
            "status_options": tracker_status_options(),
            "status_filters": tracker_status_filters(),
        }

    @app.patch("/api/tracker/{job_id}/status")
    async def update_tracker_status(
        job_id: str,
        payload: TrackerStatusUpdateRequest,
    ) -> dict[str, object]:
        """Update one tracker status from the Tracker page."""

        try:
            records = update_manual_tracker_status(app.state.base_dir, job_id, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = next((item for item in records if item.job_id == job_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Tracker record not found.")
        return {
            "record": record.model_dump(mode="json"),
            "status_options": tracker_status_options(),
            "status_filters": tracker_status_filters(),
            "message": "Tracker status updated.",
        }

    @app.get("/api/jobs")
    async def jobs() -> dict[str, object]:
        """Return saved jobs for the Jobs page selector."""

        records = sorted(
            load_jobs_index(app.state.base_dir),
            key=lambda record: (record.company.lower(), record.title.lower(), record.job_id),
        )
        return {
            "records": [record.model_dump(mode="json") for record in records],
            "status_options": tracker_status_options(),
        }

    @app.get("/api/jobs/{job_id}/workspace")
    async def job_workspace(job_id: str) -> dict[str, object]:
        """Return one saved job workspace with review artifacts and blockers."""

        job = require_job(app.state.base_dir, job_id)
        candidate_profile = load_candidate_profile(app.state.base_dir)
        requirements = load_application_requirements(app.state.base_dir, job.id)
        package = load_application_package(app.state.base_dir, job.id)
        fill_plan = load_application_fill_plan(app.state.base_dir, job.id)
        browser_use_log_dir = Path(app.state.base_dir) / RUNTIME_DATA_DIR / "browser_use"
        active_session = get_active_browser_use_session(browser_use_log_dir)
        return {
            "job": job.model_dump(mode="json"),
            "requirements": dump_optional(requirements),
            "package": dump_optional(package),
            "package_summary": build_application_package_summary(package) if package else None,
            "fill_plan": dump_optional(fill_plan),
            "fill_plan_review": build_fill_plan_review_payload(fill_plan),
            "package_blockers": get_application_package_blockers(
                candidate_profile,
                job,
                requirements,
            ),
            "fill_plan_generation_blockers": get_fill_plan_generation_blockers(
                requirements,
                package,
            ),
            "apply_blockers": get_apply_assistance_blockers(
                job,
                requirements,
                package,
                fill_plan,
                candidate_profile=candidate_profile,
            ),
            "active_browser_use_session": (
                active_session.__dict__ if active_session is not None else None
            ),
            "browser_use_runner_count": count_browser_use_runner_processes(),
        }

    @post_job_action(app, "/api/jobs/{job_id}/requirements/discover")
    async def discover_requirements(job_id: str) -> dict[str, object]:
        """Discover application requirements from the reviewed apply URL."""

        job = require_job(app.state.base_dir, job_id)
        try:
            discovery_state = run_requirements_discovery_graph(job)
            requirements = discovery_state["requirements"]
            save_application_page_snapshot(app.state.base_dir, job.id, discovery_state["snapshot"])
            save_application_requirements(app.state.base_dir, requirements)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "requirements": requirements.model_dump(mode="json"),
            "message": "Application requirements were saved for review.",
        }

    @app.put("/api/jobs/{job_id}/requirements/review")
    async def review_requirements(
        job_id: str,
        payload: RequirementsReviewRequest,
    ) -> dict[str, object]:
        """Save structured requirements review edits."""

        requirements = require_requirements(app.state.base_dir, job_id)
        try:
            reviewed = apply_application_requirements_review_edits(
                requirements,
                **payload.model_dump(),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_application_requirements(app.state.base_dir, reviewed)
        message = (
            "Requirements review saved."
            if reviewed.review_status == "reviewed"
            else (
                "Requirements were saved, but they are not reviewed because the apply "
                "page is marked as not matching this selected job."
            )
        )
        return {"requirements": reviewed.model_dump(mode="json"), "message": message}

    @post_job_action(app, "/api/jobs/{job_id}/package/generate")
    async def generate_package(job_id: str) -> dict[str, object]:
        """Generate or regenerate an application package."""

        job = require_job(app.state.base_dir, job_id)
        requirements = load_application_requirements(app.state.base_dir, job.id)
        candidate_profile = load_candidate_profile(app.state.base_dir)
        blockers = get_application_package_blockers(candidate_profile, job, requirements)
        if blockers:
            raise HTTPException(
                status_code=400,
                detail="Complete all package prerequisites before generating application material.",
            )
        try:
            package = generate_application_package(
                candidate_profile,
                load_experience_units(app.state.base_dir),
                job,
                requirements,
            )
            json_path, markdown_path = save_application_package(app.state.base_dir, package, job)
            update_tracker_for_application_package(app.state.base_dir, job.id, json_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "package": package.model_dump(mode="json"),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "message": f"Application package saved. Markdown export: {markdown_path}",
        }

    @app.put("/api/jobs/{job_id}/package/review")
    async def review_package(job_id: str, payload: PackageReviewRequest) -> dict[str, object]:
        """Save artifact text edits and mark the package reviewed."""

        job = require_job(app.state.base_dir, job_id)
        package = require_package(app.state.base_dir, job_id)
        edited = apply_application_package_review_edits(package, payload.edits_by_artifact_id)
        reviewed = mark_application_package_reviewed(edited)
        json_path, markdown_path = save_application_package(app.state.base_dir, reviewed, job)
        update_tracker_for_application_package(app.state.base_dir, job.id, json_path)
        return {
            "package": reviewed.model_dump(mode="json"),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "message": "Package review changes saved.",
        }

    @app.post("/api/jobs/{job_id}/package/export-cover-letter")
    async def export_cover_letter(
        job_id: str,
        payload: CoverLetterExportRequest,
    ) -> dict[str, object]:
        """Export the cover-letter artifact to the requested folder."""

        job = require_job(app.state.base_dir, job_id)
        package = require_package(app.state.base_dir, job_id)
        destination_text = payload.destination_folder.strip()
        if not destination_text:
            raise HTTPException(
                status_code=400,
                detail="Choose a destination folder before exporting the cover letter.",
            )
        try:
            exported_path = export_cover_letter_artifact(
                package,
                Path(destination_text).expanduser(),
            )
            json_path, markdown_path = save_application_package(app.state.base_dir, package, job)
            update_tracker_for_application_package(app.state.base_dir, job.id, json_path)
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not export cover letter artifact: {exc}",
            ) from exc
        if exported_path is None:
            raise HTTPException(
                status_code=400,
                detail="No cover letter artifact is available to export.",
            )
        return {
            "exported_path": str(exported_path),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "message": "Cover letter PDF exported.",
        }

    @post_job_action(app, "/api/jobs/{job_id}/fill-plan/generate")
    async def generate_fill_plan(job_id: str) -> dict[str, object]:
        """Generate or refresh the application fill plan."""

        requirements = load_application_requirements(app.state.base_dir, job_id)
        package = load_application_package(app.state.base_dir, job_id)
        blockers = get_fill_plan_generation_blockers(requirements, package)
        if blockers or requirements is None or package is None:
            raise HTTPException(
                status_code=400,
                detail="Complete fill plan prerequisites before generating.",
            )
        try:
            fill_plan = generate_application_fill_plan(
                load_candidate_profile(app.state.base_dir),
                requirements,
                package,
                page_snapshot=load_application_page_snapshot(app.state.base_dir, job_id),
                semantic_mapper=map_application_fields_with_llm,
            )
            saved_path = save_application_fill_plan(app.state.base_dir, fill_plan)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "fill_plan": fill_plan.model_dump(mode="json"),
            "fill_plan_review": build_fill_plan_review_payload(fill_plan),
            "saved_path": str(saved_path),
            "message": f"Application fill plan saved to {saved_path}.",
        }

    @app.put("/api/jobs/{job_id}/fill-plan/review")
    async def review_fill_plan(job_id: str, payload: FillPlanReviewRequest) -> dict[str, object]:
        """Save structured fill-plan edits and mark the plan reviewed when possible."""

        fill_plan = require_fill_plan(app.state.base_dir, job_id)
        edited = apply_fill_plan_edits(
            fill_plan,
            payload.edited_values,
            upload_paths_by_key=payload.upload_paths_by_key,
            needs_answer_values_by_key=payload.needs_answer_values_by_key,
            blocked_values_by_key=payload.blocked_values_by_key,
        )
        try:
            reviewed = mark_application_fill_plan_reviewed(edited)
        except ValueError as exc:
            save_application_fill_plan(app.state.base_dir, edited)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_application_fill_plan(app.state.base_dir, reviewed)
        update_tracker_record(app.state.base_dir, job_id, status="ready_to_apply")
        return {
            "fill_plan": reviewed.model_dump(mode="json"),
            "fill_plan_review": build_fill_plan_review_payload(reviewed),
            "message": "Fill plan review saved.",
        }

    @post_job_action(app, "/api/jobs/{job_id}/apply")
    async def apply_to_job(job_id: str) -> dict[str, object]:
        """Start Browser Use apply assistance for a reviewed job."""

        job = require_job(app.state.base_dir, job_id)
        candidate_profile = load_candidate_profile(app.state.base_dir)
        requirements = load_application_requirements(app.state.base_dir, job.id)
        package = load_application_package(app.state.base_dir, job.id)
        fill_plan = load_application_fill_plan(app.state.base_dir, job.id)
        blockers = get_apply_assistance_blockers(
            job,
            requirements,
            package,
            fill_plan,
            candidate_profile=candidate_profile,
        )
        if blockers:
            raise HTTPException(
                status_code=400,
                detail="Complete the required review steps before opening the apply flow.",
            )
        if fill_plan is None:
            raise HTTPException(
                status_code=400,
                detail="Generate and review the application fill plan before applying.",
            )
        browser_use_log_dir = Path(app.state.base_dir) / RUNTIME_DATA_DIR / "browser_use"
        try:
            result = open_apply_url_with_browser_use_fill_plan(
                str(job.apply_url),
                fill_plan=fill_plan,
                log_dir=browser_use_log_dir,
                startup_wait_seconds=API_BROWSER_USE_STARTUP_WAIT_SECONDS,
                candidate_profile=candidate_profile,
                requirements=requirements,
                package=package,
            )
        except BrowserUseLaunchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        update_tracker_record(app.state.base_dir, job.id, status="agent_assistance_attempted")
        return {
            "url": result.url,
            "pid": result.pid,
            "log_path": str(result.log_path),
            "message": f"Started Browser Use apply agent for {result.url}.",
        }

    @app.post("/api/jobs/{job_id}/browser/stop-session")
    async def stop_browser_session(job_id: str) -> dict[str, object]:
        """Stop the active Browser Use session."""

        _ = require_job(app.state.base_dir, job_id)
        browser_use_log_dir = Path(app.state.base_dir) / RUNTIME_DATA_DIR / "browser_use"
        stopped = stop_browser_use_session(browser_use_log_dir)
        message = (
            "Stopped the active Browser Use session."
            if stopped
            else "No active Browser Use session was found."
        )
        return {"stopped": stopped, "message": message}

    @app.post("/api/jobs/{job_id}/browser/kill-all")
    async def kill_browser_processes(job_id: str) -> dict[str, object]:
        """Kill all Browser Use process groups."""

        _ = require_job(app.state.base_dir, job_id)
        browser_use_log_dir = Path(app.state.base_dir) / RUNTIME_DATA_DIR / "browser_use"
        stopped_count = stop_all_browser_use_processes(browser_use_log_dir)
        return {
            "stopped_count": stopped_count,
            "message": f"Killed {stopped_count} Browser Use process group(s).",
        }

    @app.get("/api/agent")
    async def agent(
        selected_job_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Return Agent Karen page state and transcript."""

        context = build_karen_context(
            app.state.base_dir,
            current_page="Agent Karen",
            selected_job_id=selected_job_id,
            session_id=session_id,
        )
        state = run_agent_workflow(
            app.state.base_dir,
            session_id=context.session_id,
            selected_job_id=context.selected_job_id,
        )
        messages = load_agent_chat_messages(app.state.base_dir, context.session_id)
        return {
            "context": context.__dict__,
            "state": state.model_dump(mode="json"),
            "messages": [message.model_dump(mode="json") for message in messages],
            "action_labels": ACTION_LABELS,
        }

    @app.post("/api/agent/chat")
    async def agent_chat(payload: KarenChatRequest) -> dict[str, object]:
        """Process one Agent Karen chat turn."""

        result = process_karen_chat_turn(
            app.state.base_dir,
            current_page="Agent Karen",
            selected_job_id=payload.selected_job_id,
            user_message=payload.message,
            session_id=payload.session_id,
        )
        return {
            "context": result.context.__dict__,
            "intent": result.intent.model_dump(mode="json") if result.intent else None,
            "tool_result": (
                result.tool_result.model_dump(mode="json") if result.tool_result else None
            ),
        }

    return app


def post_job_action(app: FastAPI, path: str):
    """Register a POST route while keeping action functions readable."""

    return app.post(path)


def candidate_options() -> dict[str, object]:
    """Return candidate-profile select and checkbox options."""

    return {
        "employment_type": [
            ["full_time", "Full-time"],
            ["part_time", "Part-time"],
            ["contract", "Contract"],
            ["freelance", "Freelance"],
        ],
        "remote_preference": [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]],
        "work_authorization": [
            ["eu_authorized", "EU authorized"],
            ["eu_sponsorship_required", "EU sponsorship required"],
        ],
        "gender": ["Male", "Female", "Diverse"],
        "optional_document_types": {
            "reference": "Reference",
            "certificate": "Certificate",
            "other": "Other document",
        },
        "career_level": [
            ["internship", "Internship"],
            ["working_student", "Working student"],
            ["trainee", "Trainee"],
            ["junior", "Junior"],
            ["entry_level", "Entry level"],
            ["mid_level", "Mid level"],
            ["senior", "Senior"],
            ["lead", "Lead"],
            ["principal", "Principal"],
            ["manager", "Manager"],
        ],
    }


def decode_file_payload(payload: FilePayload) -> bytes:
    """Decode a base64 file payload or raise a request error."""

    try:
        return base64.b64decode(payload.content_base64)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file content is not valid base64.",
        ) from exc


def dump_optional(value: BaseModel | None) -> dict[str, object] | None:
    """Return a JSON-ready model dump for optional models."""

    if value is None:
        return None
    return value.model_dump(mode="json")


def require_job(base_dir: Path, job_id: str):
    """Load a saved normalized job or raise a 404."""

    job = load_normalized_job(base_dir, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def require_requirements(base_dir: Path, job_id: str) -> ApplicationRequirements:
    """Load application requirements or raise a 404."""

    requirements = load_application_requirements(base_dir, job_id)
    if requirements is None:
        raise HTTPException(status_code=404, detail="Application requirements not found.")
    return requirements


def require_package(base_dir: Path, job_id: str) -> ApplicationPackage:
    """Load an application package or raise a 404."""

    package = load_application_package(base_dir, job_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Application package not found.")
    return package


def require_fill_plan(base_dir: Path, job_id: str) -> ApplicationFillPlan:
    """Load an application fill plan or raise a 404."""

    fill_plan = load_application_fill_plan(base_dir, job_id)
    if fill_plan is None:
        raise HTTPException(status_code=404, detail="Application fill plan not found.")
    return fill_plan


def build_fill_plan_review_payload(
    fill_plan: ApplicationFillPlan | None,
) -> dict[str, object] | None:
    """Return stable edit keys for the structured fill-plan review UI."""

    if fill_plan is None:
        return None
    required_rows: list[dict[str, object]] = []
    optional_rows: list[dict[str, object]] = []
    for kind, index, field in fill_plan_review_rows(fill_plan):
        row = fill_plan_row_payload(kind, index, field)
        if bool(row["required"]):
            required_rows.append(row)
        else:
            optional_rows.append(row)
    upload_rows = [
        {
            "edit_key": fill_plan_upload_edit_key(upload, index),
            "label": upload.label,
            "file_path": upload.file_path,
            "document_type": upload.document_type,
            "required": upload.required,
            "source": upload.source,
            "confidence": upload.confidence,
        }
        for index, upload in enumerate(fill_plan.upload_files)
    ]
    return {
        "required_rows": required_rows,
        "optional_rows": optional_rows,
        "upload_rows": upload_rows,
    }


def fill_plan_review_rows(
    fill_plan: ApplicationFillPlan,
) -> list[
    tuple[
        str,
        int,
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField,
    ]
]:
    """Return fill-plan rows in the same grouping order as Streamlit."""

    return [
        *[
            ("field", index, field)
            for index, field in enumerate(fill_plan.field_values)
        ],
        *[
            ("needs", index, field)
            for index, field in enumerate(fill_plan.needs_answer_fields)
        ],
        *[
            ("blocked", index, field)
            for index, field in enumerate(fill_plan.blocked_fields)
        ],
    ]


def fill_plan_row_payload(
    kind: str,
    index: int,
    field: ApplicationFillFieldValue
    | ApplicationFillNeedsAnswerField
    | ApplicationFillBlockedField,
) -> dict[str, object]:
    """Return one fill-plan row with the backend edit key and default value."""

    if kind == "field":
        edit_key = fill_plan_field_edit_key(field, index)  # type: ignore[arg-type]
        value = field.value  # type: ignore[union-attr]
    elif kind == "needs":
        edit_key = fill_plan_needs_answer_edit_key(field, index)  # type: ignore[arg-type]
        value = ""
    else:
        edit_key = fill_plan_blocked_field_edit_key(field, index)  # type: ignore[arg-type]
        value = "true" if field.input_type.casefold() == "checkbox" and field.required else ""
    return {
        "kind": kind,
        "edit_key": edit_key,
        "label": field.label,
        "value": value,
        "required": field.required,
        "input_type": field.input_type,
        "options": list(field.options),
        "reason": getattr(field, "reason", ""),
        "source": field.source,
        "confidence": field.confidence,
    }


app = create_app()
