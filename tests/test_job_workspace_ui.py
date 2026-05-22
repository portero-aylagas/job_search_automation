from __future__ import annotations

from src.job_intake import create_job_listing
from src.job_workspace_ui import (
    application_package_review_has_content_changes,
    apply_application_package_review_edits,
    build_application_artifact_review_metadata,
    build_application_package_summary,
    build_review_checklist,
    deduplicate_review_items,
    get_application_fill_plan_review_blockers,
    get_apply_assistance_blockers,
    get_job_extraction_trace,
    order_application_package_artifacts_for_review,
)
from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
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


def test_apply_assistance_blocks_unresolved_needs_answer_fields() -> None:
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
        needs_answer_fields=[
            ApplicationFillNeedsAnswerField(
                label="Earliest available start date",
                reason="No safe candidate or reviewed package value is available.",
                required=True,
                input_type="text",
            )
        ],
    )

    blockers = get_apply_assistance_blockers(job, requirements, package, fill_plan)

    assert "Save reviewed values for all fields needing answers." in blockers


def test_fill_plan_review_blockers_require_resolved_needs_answer_fields() -> None:
    job = make_job()
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="draft",
        needs_answer_fields=[
            ApplicationFillNeedsAnswerField(
                label="Earliest available start date",
                reason="No safe candidate or reviewed package value is available.",
                required=True,
                input_type="text",
            )
        ],
    )

    assert get_application_fill_plan_review_blockers(fill_plan) == [
        "Save reviewed values for all fields needing answers."
    ]

    resolved_plan = fill_plan.model_copy(update={"needs_answer_fields": []})
    assert get_application_fill_plan_review_blockers(resolved_plan) == []


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


def test_review_checklist_deduplicates_repeated_sensitive_decisions() -> None:
    job = make_job()
    requirements = make_requirements(job)
    requirements.consent_requirements = [
        ApplicationRequirementFinding(
            label="Privacy policy acknowledgment required to continue",
            required=True,
        )
    ]
    requirements.screening_questions = [
        ApplicationScreeningQuestion(
            question=(
                "Haben Sie eine anerkannte Schwerbehinderung oder eine "
                "Gleichstellung nach § 2 SGB IX?"
            )
        )
    ]
    package = ApplicationPackage(
        job_id=job.id,
        status="needs_review",
        artifacts=[],
        missing_information=[
            "User decision required: Haben Sie eine anerkannte Schwerbehinderung "
            "oder eine Gleichstellung nach § 2 SGB IX?",
            "User must review consent requirement: Privacy policy acknowledgment "
            "required to continue",
        ],
        selected_experience_units=[],
        generation_notes=[],
    )

    checklist = build_review_checklist(requirements, package, None)

    assert len(checklist) == 2
    assert any("Privacy policy" in item for item in checklist)
    assert any("Schwerbehinderung" in item for item in checklist)


def test_deduplicate_review_items_groups_referral_variants() -> None:
    items = deduplicate_review_items(
        [
            "User decision required: Empfehlung durch eine/n Mitarbeiter/in",
            "A recommendation code is mentioned in visible text.",
            "Empfehlung durch eine/n Mitarbeiter/in",
        ]
    )

    assert items == ["Empfehlung durch eine/n Mitarbeiter/in"]


def test_review_checklist_skips_items_represented_by_fill_plan_fields() -> None:
    job = make_job()
    requirements = make_requirements(job)
    requirements.screening_questions = [
        ApplicationScreeningQuestion(
            question=(
                "Haben Sie eine anerkannte Schwerbehinderung oder eine "
                "Gleichstellung nach § 2 SGB IX?"
            )
        )
    ]
    package = ApplicationPackage(
        job_id=job.id,
        status="needs_review",
        artifacts=[],
        missing_information=[
            "User decision required: Haben Sie eine anerkannte Schwerbehinderung "
            "oder eine Gleichstellung nach § 2 SGB IX?"
        ],
        selected_experience_units=[],
        generation_notes=[],
    )
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        needs_answer_fields=[
            ApplicationFillNeedsAnswerField(
                label="Haben Sie eine anerkannte Schwerbehinderung?",
                reason="Sensitive user decision.",
                input_type="checkbox",
            )
        ],
    )

    assert build_review_checklist(requirements, package, fill_plan) == []


def test_application_package_summary_includes_review_context() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        status="needs_review",
        artifacts=[
            ApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Application Summary",
                content="Draft summary.",
            ),
            ApplicationArtifact(
                id="cover-letter",
                type="cover_letter",
                label="Cover Letter",
                content="Draft letter.",
            ),
        ],
        missing_information=["Candidate phone is missing."],
        selected_experience_units=["exp-001"],
        generation_notes=["Generated from reviewed requirements."],
    )

    summary = build_application_package_summary(package)

    assert summary == {
        "status": "needs_review",
        "artifact_count": 2,
        "missing_information": ["Candidate phone is missing."],
        "selected_experience_units": ["exp-001"],
        "generation_notes": ["Generated from reviewed requirements."],
    }


def test_artifact_review_metadata_includes_context_without_mutating_content() -> None:
    artifact = ApplicationArtifact(
        id="question-1",
        type="form_answer",
        label="Screening Answer 1",
        required=True,
        status="needs_review",
        content="Draft answer.",
        source_prompt="Why do you want this role?",
        source_requirement="Answer required before submit.",
    )

    metadata = build_application_artifact_review_metadata(artifact)

    assert metadata == [
        "Source prompt: Why do you want this role?",
        "Source requirement: Answer required before submit.",
    ]
    assert artifact.content == "Draft answer."


def test_package_review_orders_cover_letter_before_other_artifacts() -> None:
    summary = ApplicationArtifact(
        id="summary",
        type="application_summary",
        label="Application Summary",
        content="Draft summary.",
    )
    cover_letter = ApplicationArtifact(
        id="cover-letter-draft",
        type="cover_letter",
        label="Cover Letter Draft",
        content="Draft letter.",
    )
    notes = ApplicationArtifact(
        id="cv-tailoring-notes",
        type="cv_tailoring_notes",
        label="CV Tailoring Notes",
        content="Draft notes.",
    )

    ordered = order_application_package_artifacts_for_review([summary, cover_letter, notes])

    assert ordered == [cover_letter, summary, notes]


def test_rejected_package_status_clears_only_when_review_edits_change_content() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        status="rejected",
        artifacts=[
            ApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Summary",
                content="Draft text.",
            )
        ],
    )

    unchanged = apply_application_package_review_edits(package, {"summary": "Draft text."})
    edited = apply_application_package_review_edits(package, {"summary": "Reviewed text."})

    assert application_package_review_has_content_changes(
        package,
        {"summary": "Reviewed text."},
    )
    assert unchanged.status == "rejected"
    assert edited.status == "manually_edited"
    assert edited.artifacts[0].content == "Reviewed text."
    assert edited.artifacts[0].status == "manually_edited"


def test_get_job_extraction_trace_loads_stored_workflow_trace() -> None:
    job = make_job()
    trace = AIWorkflowTrace(
        workflow_name="job_extraction",
        operation="AI job extraction",
        model="gpt-5.4",
        profile_name="job_extraction",
        temperature=0.0,
        max_output_tokens=5000,
        timeout_seconds=90.0,
        max_retries=2,
        retry_backoff_seconds=[1.0, 2.0],
        max_tool_calls=4,
        attempt_count=1,
        duration_ms=14287,
        recorded_at="2026-05-21T21:35:03.744971+00:00",
    )
    job.job_details["job_extraction_trace"] = trace.model_dump(mode="json")

    loaded_trace = get_job_extraction_trace(job)

    assert loaded_trace == trace


def test_get_job_extraction_trace_skips_invalid_stored_trace() -> None:
    job = make_job()
    job.job_details["job_extraction_trace"] = {"workflow_name": "job_extraction"}

    assert get_job_extraction_trace(job) is None
