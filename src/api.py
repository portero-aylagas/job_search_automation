"""FastAPI adapter for the reviewed job application workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agent_chat import (
    ACTION_LABELS,
    create_agent_run_id,
    find_active_agent_run,
    load_agent_chat_messages,
    load_agent_events,
    load_agent_run,
    save_agent_run,
)
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.tools import build_karen_context
from src.app_workflow import (
    apply_url_review_messages,
    get_application_package_blockers,
    load_app_data,
    load_application_requirements,
    load_candidate_profile,
    load_jobs_index,
    load_normalized_job,
    resolved_apply_url,
)
from src.application_fill_plan import load_application_fill_plan
from src.application_fill_plan_review import build_fill_plan_review_payload
from src.application_package import (
    load_application_package,
)
from src.browser_use_launcher import (
    count_browser_use_runner_processes,
    get_active_browser_use_session,
)
from src.job_workspace import (
    build_application_package_summary,
    get_apply_assistance_blockers,
    get_fill_plan_generation_blockers,
)
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData
from src.monitoring import (
    LangSmithMonitoringError,
    compute_ai_quality_counters,
    langsmith_monitoring_summary,
)
from src.paths import RUNTIME_DATA_DIR
from src.schemas import (
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateProfile,
    KarenWorkflowRun,
)
from src.services.candidate_profile_service import (
    CandidateProfileServiceError,
    decode_uploaded_file,
    parse_uploaded_cv,
    parse_uploaded_optional_document,
    save_candidate_review_fields,
    save_reviewed_candidate_profile,
)
from src.services.candidate_profile_service import (
    delete_candidate_document as service_delete_candidate_document,
)
from src.services.candidate_profile_service import (
    save_candidate_preferences as service_save_candidate_preferences,
)
from src.services.job_workflow_service import (
    JobWorkflowServiceError,
    ReviewedJobInput,
    discover_application_requirements,
    extract_job_url,
    generate_reviewable_application_package,
    generate_reviewable_fill_plan,
    launch_apply_assistance,
    review_application_package,
    review_application_requirements,
    stop_active_browser_session,
)
from src.services.job_workflow_service import (
    archive_job as service_archive_job,
)
from src.services.job_workflow_service import (
    delete_job_data as service_delete_job_data,
)
from src.services.job_workflow_service import (
    export_cover_letter as service_export_cover_letter,
)
from src.services.job_workflow_service import (
    kill_browser_processes as service_kill_browser_processes,
)
from src.services.job_workflow_service import (
    restore_job as service_restore_job,
)
from src.services.job_workflow_service import (
    review_fill_plan as service_review_fill_plan,
)
from src.services.job_workflow_service import (
    save_reviewed_job as service_save_reviewed_job,
)
from src.services.job_workflow_service import (
    update_tracker_status as service_update_tracker_status,
)
from src.tracker_status import (
    active_tracker_records,
    tracker_status_filters,
    tracker_status_options,
)
from src.workflow.workflow_state import CurrentWorkflowState, load_current_workflow_state

PAGE_NAMES = ["Candidate Profile", "Job Intake", "Jobs", "Tracker", "Monitoring"]
BASE_DIR = Path(__file__).resolve().parent.parent
API_BROWSER_USE_STARTUP_WAIT_SECONDS = 0.0
KAREN_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="karen-run")


class FilePayload(BaseModel):
    """Browser-uploaded file encoded for JSON transport."""

    filename: str
    content_base64: str
    document_type: str = "other"


class CandidateProfilePayload(BaseModel):
    """Candidate profile payload edited by the React UI."""

    profile: CandidateProfile


class CandidateDocumentDeleteRequest(BaseModel):
    """One uploaded candidate document selected for deletion."""

    file_path: str
    document_type: str


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
    """One Karen chat turn from the Jobs side panel."""

    message: str
    selected_job_id: str | None = None
    session_id: str | None = None


def service_error_detail(
    exc: JobWorkflowServiceError | CandidateProfileServiceError,
    *,
    code: str,
    blockers: list[str] | None = None,
    field_errors: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return the structured API error detail shape for service failures."""

    message = str(exc)
    detail: dict[str, object] = {
        "code": code,
        "message": message,
        "blockers": blockers if blockers is not None else [message],
    }
    if field_errors:
        detail["field_errors"] = field_errors
    return detail


def workflow_error_detail(exc: JobWorkflowServiceError) -> dict[str, object]:
    """Return the structured error detail for workflow service blockers."""

    return service_error_detail(exc, code="workflow_error")


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

    _register_core_routes(app)
    _register_candidate_profile_routes(app)
    _register_job_workflow_routes(app)
    _register_agent_routes(app)
    return app


def _register_core_routes(app: FastAPI) -> None:
    """Register health, navigation, and monitoring endpoints."""

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Return a lightweight readiness response."""

        return {"status": "ok"}

    @app.get("/api/pages")
    async def pages() -> dict[str, list[str]]:
        """Return the top-level navigation pages."""

        return {"pages": PAGE_NAMES}

    @app.get("/api/monitoring/langsmith")
    async def langsmith_monitoring(days: int = 7) -> dict[str, object]:
        """Return a LangSmith monitoring summary for the Monitoring page."""

        try:
            return langsmith_monitoring_summary(days=days)
        except LangSmithMonitoringError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


def _register_candidate_profile_routes(app: FastAPI) -> None:
    """Register candidate-profile upload, review, and preference endpoints."""

    @app.get("/api/candidate-profile")
    async def get_candidate_profile() -> dict[str, object]:
        """Return the current candidate profile and form constants."""

        profile = load_candidate_profile(app.state.base_dir)
        return {"profile": profile.model_dump(mode="json"), "options": candidate_options()}

    @app.put("/api/candidate-profile/review-changes")
    async def save_candidate_review(payload: CandidateProfilePayload) -> dict[str, object]:
        """Persist edited CV review fields as the current candidate draft."""

        try:
            profile = save_candidate_review_fields(app.state.base_dir, payload.profile)
        except CandidateProfileServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"profile": profile.model_dump(mode="json"), "message": "CV review fields updated."}

    @app.put("/api/candidate-profile/preferences")
    async def save_candidate_preferences(payload: CandidateProfilePayload) -> dict[str, object]:
        """Persist manual candidate preference edits as the current draft."""

        profile = service_save_candidate_preferences(app.state.base_dir, payload.profile)
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "Manual preferences updated.",
        }

    @app.post("/api/candidate-profile/save")
    async def save_profile(payload: CandidateProfilePayload) -> dict[str, object]:
        """Validate and save the reviewed candidate profile."""

        try:
            profile = save_reviewed_candidate_profile(app.state.base_dir, payload.profile)
        except CandidateProfileServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved_path = Path(app.state.base_dir) / "data" / "candidate_profile.json"
        return {"profile": profile.model_dump(mode="json"), "saved_path": str(saved_path)}

    @app.post("/api/candidate-profile/parse-cv")
    async def parse_cv(payload: FilePayload) -> dict[str, object]:
        """Save an uploaded CV and parse it through the existing AI task."""

        try:
            content = decode_uploaded_file(payload.content_base64)
            profile = parse_uploaded_cv(
                app.state.base_dir,
                filename=payload.filename,
                content=content,
            )
        except CandidateProfileServiceError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "CV parsed and loaded into the review form.",
        }

    @app.post("/api/candidate-profile/parse-optional-document")
    async def parse_optional_document(payload: FilePayload) -> dict[str, object]:
        """Save and parse one optional supporting document."""

        try:
            content = decode_uploaded_file(payload.content_base64)
            profile = parse_uploaded_optional_document(
                app.state.base_dir,
                filename=payload.filename,
                document_type=payload.document_type,
                content=content,
            )
        except CandidateProfileServiceError as exc:
            raise HTTPException(status_code=500, detail=f"{payload.filename}: {exc}") from exc
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "Parsed 1 optional document into the review fields.",
        }

    @app.delete("/api/candidate-profile/document")
    async def delete_candidate_document(
        payload: CandidateDocumentDeleteRequest,
    ) -> dict[str, object]:
        """Delete one uploaded candidate document and rebuild review data."""

        try:
            profile = service_delete_candidate_document(
                app.state.base_dir,
                file_path=payload.file_path,
                document_type=payload.document_type,
            )
        except CandidateProfileServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "profile": profile.model_dump(mode="json"),
            "message": "Uploaded document deleted.",
        }

def _register_job_workflow_routes(app: FastAPI) -> None:
    """Register job intake, tracker, workspace, and workflow endpoints."""

    @app.post("/api/job-intake/extract")
    async def extract_job(payload: JobExtractionRequest) -> dict[str, object]:
        """Extract a job URL and resolve its apply URL."""

        try:
            extraction_result = extract_job_url(payload.source_url)
        except JobWorkflowServiceError as exc:
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
            job, job_path = service_save_reviewed_job(
                app.state.base_dir,
                ReviewedJobInput(
                    source_url=payload.source_url,
                    extracted_data=payload.extracted_data,
                    apply_resolution=payload.apply_resolution,
                    title=payload.title,
                    company=payload.company,
                    location=payload.location,
                    remote_policy=payload.remote_policy,
                    apply_url=payload.apply_url,
                    salary=payload.salary,
                    posted_date=payload.posted_date,
                    source_job_id=payload.source_job_id,
                    description=payload.description,
                    requirements=payload.requirements,
                    responsibilities=payload.responsibilities,
                    nice_to_have_skills=payload.nice_to_have_skills,
                    dynamic_fields=payload.dynamic_fields,
                ),
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job": job.model_dump(mode="json"),
            "job_path": str(job_path),
            "message": f"Added {job.company} / {job.title} to the workflow.",
        }

    @app.get("/api/tracker")
    async def tracker(include_archived: bool = False) -> dict[str, object]:
        """Return tracker records sorted like the Streamlit tracker."""

        _, records = load_app_data(app.state.base_dir)
        if not include_archived:
            records = active_tracker_records(records)
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
            record = service_update_tracker_status(app.state.base_dir, job_id, payload.status)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "record": record.model_dump(mode="json"),
            "status_options": tracker_status_options(),
            "status_filters": tracker_status_filters(),
            "message": "Tracker status updated.",
        }

    @app.get("/api/jobs")
    async def jobs(include_archived: bool = False) -> dict[str, object]:
        """Return saved jobs for the Jobs page selector."""

        records = load_jobs_index(app.state.base_dir)
        if not include_archived:
            records = active_tracker_records(records)
        records = sorted(
            records,
            key=lambda record: (record.company.lower(), record.title.lower(), record.job_id),
        )
        return {
            "records": [record.model_dump(mode="json") for record in records],
            "status_options": tracker_status_options(),
        }

    @app.post("/api/jobs/{job_id}/archive")
    async def archive_job(job_id: str) -> dict[str, object]:
        """Remove one job from active Jobs and Tracker views."""

        try:
            record = service_archive_job(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "record": record.model_dump(mode="json") if record else None,
            "message": "Job removed from active jobs.",
        }

    @app.post("/api/jobs/{job_id}/restore")
    async def restore_job(job_id: str) -> dict[str, object]:
        """Restore one archived job to active Jobs and Tracker views."""

        try:
            record = service_restore_job(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "record": record.model_dump(mode="json") if record else None,
            "message": "Job restored to active jobs.",
        }

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, object]:
        """Permanently delete one job's local data and tracker entry."""

        try:
            records = service_delete_job_data(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "records": [record.model_dump(mode="json") for record in records],
            "message": "Job data permanently deleted.",
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
        package_blockers = get_application_package_blockers(
            candidate_profile,
            job,
            requirements,
        )
        fill_plan_generation_blockers = get_fill_plan_generation_blockers(
            requirements,
            package,
        )
        apply_blockers = get_apply_assistance_blockers(
            job,
            requirements,
            package,
            fill_plan,
            candidate_profile=candidate_profile,
        )
        return {
            "job": job.model_dump(mode="json"),
            "requirements": dump_optional(requirements),
            "package": dump_optional(package),
            "package_summary": build_application_package_summary(package) if package else None,
            "fill_plan": dump_optional(fill_plan),
            "fill_plan_review": build_fill_plan_review_payload(fill_plan),
            "ai_quality_counters": compute_ai_quality_counters(
                job=job,
                requirements=requirements,
                package=package,
                fill_plan=fill_plan,
                apply_blockers=apply_blockers,
            ).model_dump(mode="json"),
            "package_blockers": package_blockers,
            "fill_plan_generation_blockers": fill_plan_generation_blockers,
            "apply_blockers": apply_blockers,
            "active_browser_use_session": (
                active_session.__dict__ if active_session is not None else None
            ),
            "browser_use_runner_count": count_browser_use_runner_processes(),
        }

    @post_job_action(app, "/api/jobs/{job_id}/requirements/discover")
    async def discover_requirements(job_id: str) -> dict[str, object]:
        """Discover application requirements from the reviewed apply URL."""

        try:
            requirements = discover_application_requirements(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
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

        try:
            reviewed = review_application_requirements(
                app.state.base_dir,
                job_id,
                **payload.model_dump(),
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
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

        try:
            package, json_path, markdown_path = generate_reviewable_application_package(
                app.state.base_dir,
                job_id,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
        return {
            "package": package.model_dump(mode="json"),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "message": f"Application package saved. Markdown export: {markdown_path}",
        }

    @app.put("/api/jobs/{job_id}/package/review")
    async def review_package(job_id: str, payload: PackageReviewRequest) -> dict[str, object]:
        """Save artifact text edits and mark the package reviewed."""

        try:
            reviewed, json_path, markdown_path = review_application_package(
                app.state.base_dir,
                job_id,
                payload.edits_by_artifact_id,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
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

        try:
            exported_path, json_path, markdown_path = service_export_cover_letter(
                app.state.base_dir,
                job_id,
                payload.destination_folder,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
        return {
            "exported_path": str(exported_path),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "message": "Cover letter PDF exported.",
        }

    @post_job_action(app, "/api/jobs/{job_id}/fill-plan/generate")
    async def generate_fill_plan(job_id: str) -> dict[str, object]:
        """Generate or refresh the application fill plan."""

        try:
            fill_plan, saved_path = generate_reviewable_fill_plan(
                app.state.base_dir,
                job_id,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
        return {
            "fill_plan": fill_plan.model_dump(mode="json"),
            "fill_plan_review": build_fill_plan_review_payload(fill_plan),
            "saved_path": str(saved_path),
            "message": f"Application fill plan saved to {saved_path}.",
        }

    @app.put("/api/jobs/{job_id}/fill-plan/review")
    async def review_fill_plan(job_id: str, payload: FillPlanReviewRequest) -> dict[str, object]:
        """Save structured fill-plan edits and mark the plan reviewed when possible."""

        try:
            reviewed = service_review_fill_plan(
                app.state.base_dir,
                job_id,
                edited_values=payload.edited_values,
                upload_paths_by_key=payload.upload_paths_by_key,
                needs_answer_values_by_key=payload.needs_answer_values_by_key,
                blocked_values_by_key=payload.blocked_values_by_key,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
        return {
            "fill_plan": reviewed.model_dump(mode="json"),
            "fill_plan_review": build_fill_plan_review_payload(reviewed),
            "message": "Fill plan review saved.",
        }

    @post_job_action(app, "/api/jobs/{job_id}/apply")
    async def apply_to_job(job_id: str) -> dict[str, object]:
        """Start Browser Use apply assistance for a reviewed job."""

        try:
            result = launch_apply_assistance(
                app.state.base_dir,
                job_id,
                startup_wait_seconds=API_BROWSER_USE_STARTUP_WAIT_SECONDS,
            )
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=400, detail=workflow_error_detail(exc)) from exc
        return {
            "url": result.url,
            "pid": result.pid,
            "log_path": str(result.log_path),
            "message": f"Started Browser Use apply agent for {result.url}.",
        }

    @app.post("/api/jobs/{job_id}/browser/stop-session")
    async def stop_browser_session(job_id: str) -> dict[str, object]:
        """Stop the active Browser Use session."""

        try:
            _ = require_job(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        stopped = stop_active_browser_session(app.state.base_dir)
        message = (
            "Stopped the active Browser Use session."
            if stopped
            else "No active Browser Use session was found."
        )
        return {"stopped": stopped, "message": message}

    @app.post("/api/jobs/{job_id}/browser/kill-all")
    async def kill_browser_processes(job_id: str) -> dict[str, object]:
        """Kill all Browser Use process groups."""

        try:
            _ = require_job(app.state.base_dir, job_id)
        except JobWorkflowServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        stopped_count = service_kill_browser_processes(app.state.base_dir)
        return {
            "stopped_count": stopped_count,
            "message": f"Killed {stopped_count} Browser Use process group(s).",
        }


def _register_agent_routes(app: FastAPI) -> None:
    """Register Karen agent state, chat, and run polling endpoints."""

    @app.get("/api/agent")
    async def agent(
        selected_job_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Return Karen side-panel state and transcript."""

        context = build_karen_context(
            app.state.base_dir,
            current_page="Jobs",
            selected_job_id=selected_job_id,
            session_id=session_id,
        )
        state = load_current_workflow_state(app.state.base_dir, context.selected_job_id)
        messages = load_agent_chat_messages(app.state.base_dir, context.session_id)
        events = _agent_events_payload(
            app.state.base_dir,
            context.session_id,
            context.selected_job_id,
        )
        return {
            "context": context.model_dump(mode="json"),
            "state": _agent_state_payload(context.session_id, state),
            "messages": [message.model_dump(mode="json") for message in messages],
            "events": events,
            "action_labels": ACTION_LABELS,
        }

    @app.post("/api/agent/chat")
    async def agent_chat(payload: KarenChatRequest) -> dict[str, object]:
        """Process one Karen side-panel chat turn."""

        context = build_karen_context(
            app.state.base_dir,
            current_page="Jobs",
            selected_job_id=payload.selected_job_id,
            session_id=payload.session_id,
        )
        active_run = find_active_agent_run(
            app.state.base_dir,
            session_id=context.session_id,
            job_id=context.selected_job_id,
        )
        if active_run is not None:
            return {
                "context": context.model_dump(mode="json"),
                "intent": None,
                "tool_result": None,
                "run": active_run.model_dump(mode="json"),
                "run_id": active_run.run_id,
                "status": active_run.status,
                "reused_run": True,
            }
        run = KarenWorkflowRun(
            run_id=create_agent_run_id(),
            session_id=context.session_id,
            job_id=context.selected_job_id,
            status="running",
        )
        save_agent_run(app.state.base_dir, run)
        KAREN_RUN_EXECUTOR.submit(
            partial(
                _run_karen_chat_background,
                app.state.base_dir,
                current_page="Jobs",
                selected_job_id=context.selected_job_id,
                user_message=payload.message,
                session_id=context.session_id,
                workflow_run_id=run.run_id,
            ),
        )
        return {
            "context": context.model_dump(mode="json"),
            "intent": None,
            "tool_result": None,
            "run": run.model_dump(mode="json"),
            "run_id": run.run_id,
            "status": run.status,
        }

    @app.get("/api/agent/runs/{run_id}")
    async def agent_run(run_id: str) -> dict[str, object]:
        """Return current status and progress events for one Karen run."""

        run = load_agent_run(app.state.base_dir, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Karen workflow run not found.")
        return _agent_run_payload(app.state.base_dir, run)


def _run_karen_chat_background(
    base_dir: Path,
    *,
    current_page: str,
    selected_job_id: str | None,
    user_message: str,
    session_id: str,
    workflow_run_id: str,
) -> None:
    """Run one Karen chat turn outside the request/response lifecycle."""

    run = load_agent_run(base_dir, workflow_run_id)
    if run is None:
        run = KarenWorkflowRun(
            run_id=workflow_run_id,
            session_id=session_id,
            job_id=selected_job_id,
            status="running",
        )
    try:
        result = process_karen_chat_turn(
            base_dir,
            current_page=current_page,
            selected_job_id=selected_job_id,
            user_message=user_message,
            session_id=session_id,
            workflow_run_id=workflow_run_id,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        run.status = "error"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        run.final_message = f"Karen workflow failed: {exc}"
        save_agent_run(base_dir, run)
        return

    run.job_id = result.context.selected_job_id
    result_status = result.tool_result.status if result.tool_result else "completed"
    run.status = _run_status_from_chat_result(result_status)
    run.current_action = None
    run.finished_at = datetime.now(timezone.utc).isoformat()
    run.final_message = result.assistant_message
    save_agent_run(base_dir, run)


def _run_status_from_chat_result(status: str) -> str:
    if status in {"blocked", "needs_job"}:
        return "blocked"
    if status in {"needs_input", "waiting_for_review"}:
        return "needs_input"
    if status in {"refused"}:
        return "refused"
    if status in {"error"}:
        return "error"
    return "completed"


def _agent_run_payload(base_dir: Path | str, run: KarenWorkflowRun) -> dict[str, object]:
    """Return run status plus the latest visible Karen side-panel state."""

    events = [
        event
        for event in load_agent_events(base_dir, run.session_id)
        if event.run_id == run.run_id or event.details.get("workflow_run_id") == run.run_id
    ]
    current_action = _current_action_from_events(events)
    run_payload = run.model_copy(update={"current_action": current_action})
    state = load_current_workflow_state(base_dir, run.job_id)
    messages = load_agent_chat_messages(base_dir, run.session_id)
    return {
        "run": run_payload.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in events[-50:]],
        "context": {
            "session_id": run.session_id,
            "selected_job_id": run.job_id,
        },
        "state": _agent_state_payload(run.session_id, state),
        "messages": [message.model_dump(mode="json") for message in messages],
        "action_labels": ACTION_LABELS,
    }


def _current_action_from_events(events: list[object]) -> str | None:
    for event in reversed(events):
        status = getattr(event, "status", "") or getattr(event, "result", "")
        if status == "running" or getattr(event, "result", "") == "started":
            return getattr(event, "action", None)
        if status in {"completed", "blocked", "needs_input", "refused", "error"}:
            return None
    return None


def _agent_state_payload(
    session_id: str,
    state: CurrentWorkflowState,
) -> dict[str, object]:
    """Return the `/api/agent` state shape from the shared workflow state."""

    payload = state.model_dump(mode="json")
    payload.update(
        {
            "session_id": session_id,
            "artifacts_present": {
                "normalized_job": state.job_exists,
                "application_requirements": state.requirements_exists,
                "application_package": state.package_exists,
                "application_fill_plan": state.fill_plan_exists,
            },
            "blockers": list(state.current_blockers),
            "errors": [],
        }
    )
    return payload


def _agent_events_payload(
    base_dir: Path | str,
    session_id: str,
    selected_job_id: str | None,
) -> list[dict[str, object]]:
    """Return recent workflow events for the current session and job."""

    events = load_agent_events(base_dir, session_id)
    if selected_job_id:
        events = [
            event
            for event in events
            if event.job_id in {None, selected_job_id}
        ]
    return [event.model_dump(mode="json") for event in events[-50:]]


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


def dump_optional(value: BaseModel | None) -> dict[str, object] | None:
    """Return a JSON-ready model dump for optional models."""

    if value is None:
        return None
    return value.model_dump(mode="json")


def require_job(base_dir: Path, job_id: str):
    """Load a saved normalized job or raise a 404."""

    ensure_job_is_active(base_dir, job_id)
    job = load_normalized_job(base_dir, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def ensure_job_is_active(base_dir: Path, job_id: str) -> None:
    """Reject direct workflow access for archived jobs."""

    record = next((item for item in load_jobs_index(base_dir) if item.job_id == job_id), None)
    if record is not None and record.archived_at:
        raise HTTPException(
            status_code=400,
            detail="Restore this archived job before running workflow actions.",
        )


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


app = create_app()
