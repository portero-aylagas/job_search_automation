from __future__ import annotations

from src.job_intake import create_job_listing
from src.job_workspace_ui import get_apply_assistance_blockers
from src.schemas import (
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateProfile,
)


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        description="Build automation workflows.",
    )


def make_requirements(
    job,
    *,
    status: str = "discovered",
    review_status: str = "reviewed",
    job_preserving: bool = True,
) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status=status,
        review_status=review_status,
        job_preserving=job_preserving,
    )


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {"file_path": "/tmp/cv.pdf", "parsed": True},
                },
                "cv_extracted": {
                    "identity": {
                        "full_name": "Taylor Rivera",
                        "email": "taylor@example.com",
                    },
                },
                "candidate_preferences": {
                    "target_roles": ["Automation Engineer"],
                    "target_locations": ["Remote"],
                    "remote_preference": ["remote"],
                    "employment_type": ["full_time"],
                    "seniority_level": ["junior"],
                    "availability": "Immediately",
                    "salary_min_eur": 55000,
                    "salary_max_eur": 65000,
                    "work_authorization": "eu_authorized",
                },
            }
        }
    )


def test_apply_assistance_blockers_require_reviewed_requirements() -> None:
    job = make_job()

    blockers = get_apply_assistance_blockers(
        job,
        make_requirements(job, review_status="draft"),
        None,
        None,
    )

    assert "Review the discovered application requirements." in blockers
    assert "Generate the application package before applying." in blockers
    assert "Generate the application fill plan before applying." in blockers


def test_apply_assistance_blockers_reject_blocked_requirements() -> None:
    job = make_job()

    blockers = get_apply_assistance_blockers(
        job,
        make_requirements(job, status="blocked", job_preserving=False),
        None,
        None,
    )

    assert "Resolve reviewed application requirements before applying." in blockers


def test_apply_assistance_has_no_blockers_with_reviewed_data() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(
        job_id=job.id,
        status="draft",
        artifacts=[],
        missing_information=[],
        selected_experience_units=[],
        generation_notes=[],
    )
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="reviewed",
    )

    blockers = get_apply_assistance_blockers(job, requirements, package, fill_plan)

    assert blockers == []


def test_apply_assistance_blocks_missing_or_unreviewed_fill_plan() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(
        job_id=job.id,
        status="draft",
        artifacts=[],
        missing_information=[],
        selected_experience_units=[],
        generation_notes=[],
    )

    blockers = get_apply_assistance_blockers(job, requirements, package, None)

    assert "Generate the application fill plan before applying." in blockers

    draft_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="draft",
    )

    blockers = get_apply_assistance_blockers(job, requirements, package, draft_plan)

    assert "Review the application fill plan before applying." in blockers


def test_apply_assistance_blocks_rejected_package() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(
        job_id=job.id,
        status="rejected",
        artifacts=[],
        missing_information=[],
        selected_experience_units=[],
        generation_notes=[],
    )

    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="reviewed",
    )

    blockers = get_apply_assistance_blockers(job, requirements, package, fill_plan)

    assert "Regenerate or manually edit the rejected application package." in blockers
