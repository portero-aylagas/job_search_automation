from __future__ import annotations

from pathlib import Path

from src.application_fill_plan import (
    generate_application_fill_plan,
    mark_application_fill_plan_reviewed,
)
from src.job_intake import create_job_listing
from src.job_workspace import (
    application_artifact_review_key,
    application_package_review_has_content_changes,
    apply_application_package_review_edits,
    apply_application_requirements_review_edits,
    build_application_artifact_review_metadata,
    build_application_package_summary,
    build_package_review_saved_message,
    build_review_checklist,
    deduplicate_review_items,
    get_apply_assistance_blockers,
    get_fill_plan_generation_blockers,
    get_job_extraction_trace,
    mark_application_package_reviewed,
    order_application_package_artifacts_for_review,
)
from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFormField,
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


def test_apply_assistance_has_no_blockers_with_reviewed_data() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(job_id=job.id, status="approved", artifacts=[])
    fill_plan = ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="reviewed",
    )

    assert get_apply_assistance_blockers(job, requirements, package, fill_plan) == []


def test_apply_assistance_blocks_stale_reviewed_fill_plan_until_refresh() -> None:
    job = make_job()
    profile = make_profile()
    requirements = make_requirements(job)
    requirements.motivation_letter = ApplicationRequirementFinding(
        label="Optional cover letter",
        required=False,
        evidence="You may upload a cover letter.",
        confidence="medium",
    )
    package = ApplicationPackage(
        job_id=job.id,
        status="approved",
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                content="Dear hiring team.",
            )
        ],
    )
    fill_plan = mark_application_fill_plan_reviewed(
        generate_application_fill_plan(profile, requirements, package)
    )
    package.artifacts[0].metadata["generated_file_path"] = "/tmp/cover_letter.pdf"

    blockers = get_apply_assistance_blockers(
        job,
        requirements,
        package,
        fill_plan,
        candidate_profile=profile,
    )

    assert blockers == [
        "Refresh the application fill plan because application package upload "
        "artifacts changed since review."
    ]


def test_fill_plan_generation_blocks_unreviewed_package() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(job_id=job.id, status="draft", artifacts=[])

    assert get_fill_plan_generation_blockers(requirements, package) == [
        "Save the application package review."
    ]


def test_apply_assistance_blocks_unresolved_needs_answer_fields() -> None:
    job = make_job()
    requirements = make_requirements(job)
    package = ApplicationPackage(job_id=job.id, status="approved", artifacts=[])
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

    assert get_apply_assistance_blockers(job, requirements, package, fill_plan) == [
        "Save reviewed values for all fields needing answers."
    ]


def test_application_requirements_review_edits_mark_requirements_reviewed() -> None:
    job = make_job()
    requirements = make_requirements(job, review_status="draft")
    requirements.required_documents = [
        ApplicationRequirementFinding(label="CV", required=True, confidence="high")
    ]
    requirements.profile_fields = [
        ApplicationFormField(label="Email", required=True, input_type="email")
    ]
    requirements.screening_questions = [
        ApplicationScreeningQuestion(
            question="Are you authorized to work in Germany?",
            required=True,
            input_type="select",
        )
    ]

    reviewed = apply_application_requirements_review_edits(
        requirements,
        job_preserving=True,
        confidence="high",
        blocked_reason="",
        required_documents_text="- [required] CV or resume",
        upload_expectations_text="",
        motivation_label="Cover letter",
        motivation_required=False,
        profile_fields_text="- [required] Email address | email",
        screening_questions_text="- [required] Work authorization | select",
        custom_form_fields_text="- [optional] Portfolio URL | url",
        consent_requirements_text="- [required] Privacy consent",
        privacy_login_ats_gates_text="",
        deadlines_text="",
        contact_or_fallback_text="",
        missing_or_uncertain_text="- Confirm earliest start date",
    )

    assert reviewed.review_status == "reviewed"
    assert reviewed.status == "discovered"
    assert reviewed.required_documents[0].label == "CV or resume"
    assert reviewed.profile_fields[0].label == "Email address"
    assert reviewed.screening_questions[0].question == "Work authorization"
    assert reviewed.custom_form_fields[0].required is False
    assert reviewed.motivation_letter is not None
    assert reviewed.consent_requirements[0].label == "Privacy consent"
    assert reviewed.missing_or_uncertain == ["Confirm earliest start date"]


def test_application_requirements_review_edits_keep_unmatched_page_unreviewed() -> None:
    job = make_job()
    requirements = make_requirements(job, review_status="draft")

    reviewed = apply_application_requirements_review_edits(
        requirements,
        job_preserving=False,
        confidence="low",
        blocked_reason="Apply page does not match this job.",
        required_documents_text="",
        upload_expectations_text="",
        motivation_label="",
        motivation_required=False,
        profile_fields_text="",
        screening_questions_text="",
        custom_form_fields_text="",
        consent_requirements_text="",
        privacy_login_ats_gates_text="",
        deadlines_text="",
        contact_or_fallback_text="",
        missing_or_uncertain_text="",
    )

    assert reviewed.status == "blocked"
    assert reviewed.review_status == "draft"
    assert reviewed.blocked_reason == "Apply page does not match this job."


def test_mark_application_package_reviewed_approves_package_and_artifacts() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        status="needs_review",
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                status="needs_review",
                content="Dear hiring team.",
            )
        ],
    )

    reviewed = mark_application_package_reviewed(package)

    assert reviewed.status == "approved"
    assert reviewed.artifacts[0].status == "approved"
    assert package.status == "needs_review"


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


def test_deduplicate_review_items_groups_referral_variants() -> None:
    items = deduplicate_review_items(
        [
            "User decision required: employee referral",
            "Optional consent for recommendation code",
            "Empfehlung durch Mitarbeitende",
        ]
    )

    assert items == ["employee referral"]


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

    assert build_application_package_summary(package) == {
        "status": "needs_review",
        "artifact_count": 2,
        "missing_information": ["Candidate phone is missing."],
        "selected_experience_units": ["exp-001"],
        "generation_notes": ["Generated from reviewed requirements."],
    }


def test_package_review_saved_message_lists_exports() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                content="Dear hiring team.",
                metadata={"generated_file_path": "/tmp/cover_letter.pdf"},
            )
        ],
    )

    message = build_package_review_saved_message(
        Path("/tmp/application_package.json"),
        Path("/tmp/application_package.md"),
        package,
    )

    assert "Package review changes saved." in message
    assert "- Package JSON: /tmp/application_package.json" in message
    assert "- Markdown export: /tmp/application_package.md" in message
    assert "- Cover letter PDF artifact: /tmp/cover_letter.pdf" in message


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

    assert build_application_artifact_review_metadata(artifact) == [
        "Source prompt: Why do you want this role?",
        "Source requirement: Answer required before submit.",
    ]
    assert artifact.content == "Draft answer."


def test_artifact_review_key_changes_when_generated_content_changes() -> None:
    first_artifact = ApplicationArtifact(
        id="cover-letter-draft",
        type="cover_letter",
        label="Cover Letter Draft",
        content="Previous reviewed letter.",
    )
    regenerated_artifact = first_artifact.model_copy(
        update={"content": "Freshly generated letter."}
    )

    first_key = application_artifact_review_key("job-001", first_artifact)
    regenerated_key = application_artifact_review_key("job-001", regenerated_artifact)

    assert first_key.startswith("application_package_review_job-001_cover-letter-draft_")
    assert regenerated_key.startswith("application_package_review_job-001_cover-letter-draft_")
    assert regenerated_key != first_key


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

    assert get_job_extraction_trace(job) == trace


def test_get_job_extraction_trace_skips_invalid_stored_trace() -> None:
    job = make_job()
    job.job_details["job_extraction_trace"] = {"workflow_name": "job_extraction"}

    assert get_job_extraction_trace(job) is None
