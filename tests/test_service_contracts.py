from __future__ import annotations

from pathlib import Path

import pytest

import src.services.job_workflow_service as job_service
from src.app_workflow import (
    load_application_page_snapshot,
    load_application_requirements,
    load_candidate_profile,
    load_jobs_index,
    save_candidate_profile,
)
from src.application_fill_plan import load_application_fill_plan, save_application_fill_plan
from src.application_package import load_application_package
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import (
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateOptionalDocument,
    CandidateProfile,
)
from src.services.candidate_profile_service import (
    CandidateProfileServiceError,
    delete_candidate_document,
    save_candidate_review_fields,
)
from src.services.job_workflow_service import (
    JobWorkflowServiceError,
    discover_application_requirements,
    generate_reviewable_application_package,
    review_application_package,
    review_fill_plan,
)


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        description="Build automation workflows.",
    )


def make_requirements(job, *, review_status: str = "draft") -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status="discovered",
        review_status=review_status,
        job_preserving=True,
    )


def complete_candidate_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {
                        "file_path": "data/runtime/candidate_profile/cv/cv.txt",
                        "parsed": True,
                    },
                    "optional_documents": [],
                },
                "cv_extracted": {
                    "identity": {
                        "first_name": "Taylor",
                        "last_name": "Rivera",
                        "gender": "Female",
                        "email": "taylor@example.com",
                        "phone": "+49170123456",
                        "street_address": "Example Street",
                        "street_number": "12",
                        "postal_code": "10115",
                        "city": "Berlin",
                        "country": "Germany",
                        "nationality": "Spanish",
                    },
                    "work_experience": ["Built automation workflows."],
                    "skills": ["Python", "Testing"],
                    "languages": ["English", "German"],
                },
            }
        }
    )


def test_discover_application_requirements_service_persists_mocked_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)
    snapshot = ApplicationPageSnapshot(
        requested_url=str(job.apply_url),
        final_url=str(job.apply_url),
        page_title="Apply",
        evidence_matches=["Upload your CV."],
    )
    requirements = make_requirements(job)

    monkeypatch.setattr(
        job_service,
        "run_requirements_discovery_graph",
        lambda received_job: {
            "snapshot": snapshot,
            "requirements": requirements,
        },
    )

    discovered = discover_application_requirements(tmp_path, job.id)

    assert discovered == requirements
    assert load_application_requirements(tmp_path, job.id) == requirements
    assert load_application_page_snapshot(tmp_path, job.id) == snapshot
    assert load_jobs_index(tmp_path)[0].job_id == job.id


def test_review_application_package_missing_package_raises_service_error(
    tmp_path: Path,
) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)

    with pytest.raises(JobWorkflowServiceError, match="Application package not found"):
        review_application_package(tmp_path, job.id, edits_by_artifact_id={})

    assert load_application_package(tmp_path, job.id) is None


def test_generate_package_with_blockers_writes_no_partial_package(tmp_path: Path) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)

    with pytest.raises(
        JobWorkflowServiceError,
        match="Complete all package prerequisites",
    ):
        generate_reviewable_application_package(tmp_path, job.id)

    assert load_application_package(tmp_path, job.id) is None


def test_failed_fill_plan_review_preserves_draft_with_blocker_context(
    tmp_path: Path,
) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        needs_answer_fields=[
            ApplicationFillNeedsAnswerField(
                label="Earliest start date",
                reason="Needs reviewer input.",
                required=True,
                input_type="text",
            )
        ],
    )
    save_application_fill_plan(tmp_path, fill_plan)

    with pytest.raises(
        JobWorkflowServiceError,
        match="Save reviewed values for all fields needing answers",
    ):
        review_fill_plan(
            tmp_path,
            job.id,
            edited_values={},
            upload_paths_by_key={},
            needs_answer_values_by_key={},
            blocked_values_by_key={},
        )

    saved = load_application_fill_plan(tmp_path, job.id)
    assert saved is not None
    assert saved.review_status == "draft"
    assert saved.needs_answer_fields[0].label == "Earliest start date"
    assert saved.needs_answer_fields[0].required is True


def test_candidate_review_invalid_email_does_not_overwrite_saved_profile(
    tmp_path: Path,
) -> None:
    profile = complete_candidate_profile()
    save_candidate_profile(tmp_path, profile)
    edited = profile.model_copy(deep=True)
    edited.candidate_profile.cv_extracted.identity.email = "not-an-email"

    with pytest.raises(CandidateProfileServiceError, match="valid address"):
        save_candidate_review_fields(tmp_path, edited)

    saved = load_candidate_profile(tmp_path)
    assert saved.candidate_profile.cv_extracted.identity.email == "taylor@example.com"


def test_candidate_document_delete_rejects_dangerous_saved_path(tmp_path: Path) -> None:
    outside_path = tmp_path / "data" / "runtime" / "secret.txt"
    outside_path.parent.mkdir(parents=True)
    outside_path.write_text("secret", encoding="utf-8")
    profile = complete_candidate_profile()
    profile.candidate_profile.source_documents.optional_documents = [
        CandidateOptionalDocument(
            file_path=str(outside_path),
            file_name="secret.txt",
            document_type="reference",
            parsed=True,
        )
    ]
    save_candidate_profile(tmp_path, profile)

    with pytest.raises(CandidateProfileServiceError, match="candidate_profile"):
        delete_candidate_document(
            tmp_path,
            file_path=str(outside_path),
            document_type="reference",
        )

    assert outside_path.exists()
    saved = load_candidate_profile(tmp_path)
    assert len(saved.candidate_profile.source_documents.optional_documents) == 1
