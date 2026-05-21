import pytest

from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
    ApplicationPackage,
    ApplicationRequirements,
    CandidatePreferences,
    CandidateProfile,
    JobListing,
    TrackerRecord,
)


def test_candidate_profile_round_trip() -> None:
    profile = CandidateProfile(
        candidate_profile={
            "profile_status": "draft",
            "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
            "cv_extracted": {
                "identity": {
                    "full_name": "Taylor Rivera",
                    "first_name": "Taylor",
                    "last_name": "Rivera",
                    "email": "taylor@example.com",
                    "phone": "+49 123 456",
                    "location": "Remote",
                    "street_address": "Example Street",
                    "street_number": "12",
                    "postal_code": "10115",
                    "city": "Berlin",
                    "country": "Germany",
                    "nationality": "Spanish",
                    "linkedin_url": "https://linkedin.com/in/taylor",
                    "github_url": "https://github.com/taylor",
                    "portfolio_url": "",
                },
                "work_experience": ["Automation workflows"],
                "education": ["BSc Computer Science"],
                "skills": ["Python", "APIs"],
                "languages": ["English"],
                "certifications": [],
                "projects": [],
            },
            "candidate_preferences": {
                "target_roles": ["Automation Engineer"],
                "target_locations": ["Remote"],
                "remote_preference": ["remote", "hybrid"],
                "employment_type": ["full_time"],
                "seniority_level": ["mid_level", "senior"],
                "availability": "Immediately",
                "salary_min_eur": 60000,
                "salary_max_eur": 70000,
                "work_authorization": "eu_authorized",
            },
        },
    )

    reloaded = CandidateProfile.model_validate(profile.model_dump(mode="json"))

    assert reloaded == profile


def test_candidate_identity_splits_legacy_full_name_and_normalizes_contact() -> None:
    profile = CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "cv_extracted": {
                    "identity": {
                        "full_name": " Taylor Rivera ",
                        "email": " TAYLOR@EXAMPLE.COM ",
                        "phone": " 00 49 170 123 456 ",
                    },
                },
            },
        }
    )

    identity = profile.candidate_profile.cv_extracted.identity
    assert identity.first_name == "Taylor"
    assert identity.last_name == "Rivera"
    assert identity.email == "taylor@example.com"
    assert identity.phone == "+49170123456"


def test_candidate_profile_coerces_legacy_optional_document_paths() -> None:
    profile = CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "optional_documents": [
                        "data/runtime/candidate_profile/optional_documents/reference.pdf"
                    ],
                },
            },
        }
    )

    optional_document = profile.candidate_profile.source_documents.optional_documents[0]
    assert optional_document.file_path.endswith("reference.pdf")
    assert optional_document.file_name == "reference.pdf"
    assert optional_document.document_type == "other"
    assert optional_document.parsed is False


def test_supplemental_extraction_round_trip_includes_workflow_trace() -> None:
    from src.schemas import CandidateSupplementalExtracted

    trace = AIWorkflowTrace(
        workflow_name="optional_document_extraction",
        operation="AI optional document extraction",
        model="gpt-5.4",
        profile_name="optional_document_extraction",
        temperature=0.0,
        max_output_tokens=3000,
        timeout_seconds=60,
        max_retries=2,
        retry_backoff_seconds=[1.0, 2.0],
    )
    supplemental = CandidateSupplementalExtracted(
        certifications=["Cloud Fundamentals"],
        notes=["Reference available."],
        workflow_trace=trace,
    )

    reloaded = CandidateSupplementalExtracted.model_validate(
        supplemental.model_dump(mode="json")
    )

    assert reloaded == supplemental


def test_candidate_preferences_coerces_legacy_strings() -> None:
    preferences = CandidatePreferences.model_validate(
        {
            "target_roles": ["Automation Engineer"],
            "target_locations": ["Remote"],
            "remote_preference": "Hybrid",
            "employment_type": ["full_time", "trainee", "working_student"],
            "seniority_level": "Entry Level, Lead",
            "availability": "Immediately",
            "salary_min_eur": "60000",
            "salary_max_eur": "70000",
            "work_authorization": "EU sponsorship required",
        }
    )

    assert preferences.remote_preference == ["hybrid"]
    assert preferences.seniority_level == [
        "entry_level",
        "lead",
        "trainee",
        "working_student",
    ]
    assert preferences.employment_type == ["full_time"]
    assert preferences.salary_min_eur == 60000
    assert preferences.salary_max_eur == 70000
    assert preferences.work_authorization == "eu_sponsorship_required"


def test_tracker_record_accepts_known_statuses() -> None:
    record = TrackerRecord(
        job_id="job-123",
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        location="Berlin",
        retrieval_mode="url",
        match_score=88.5,
        status="application_draft",
        notes="Ready for package generation.",
    )

    assert record.status == "application_draft"


def test_job_listing_rejects_apply_url_that_matches_source_url() -> None:
    source_url = "https://example.com/jobs/job-description.185158.html"

    try:
        JobListing(
            id="job-123",
            title="Automation Engineer",
            company="Example Co",
            source_url=source_url,
            retrieval_mode="url",
            apply_url=source_url,
        )
    except ValueError as exc:
        assert "application destination" in str(exc)
    else:
        raise AssertionError("JobListing should reject apply_url matching source_url.")


def test_job_listing_allows_distinct_apply_url() -> None:
    listing = JobListing(
        id="job-123",
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/job-description.185158.html",
        retrieval_mode="url",
        apply_url="https://apply.example.com/start/job-description.185158",
    )

    assert str(listing.apply_url).startswith("https://apply.example.com/start/")


def test_job_listing_normalizes_dynamic_job_details() -> None:
    listing = JobListing(
        id="job-123",
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/job-description.185158.html",
        retrieval_mode="url",
        job_details={
            "dynamic_fields": [
                {
                    "dynamic": True,
                    "name": " Hiring team ",
                    "value": "Platform",
                }
            ]
        },
    )

    assert listing.job_details["dynamic_fields"] == [
        {
            "dynamic": True,
            "name": "Hiring team",
            "value": "Platform",
            "category": "",
            "source_text": "",
            "confidence": "medium",
        }
    ]


def test_job_listing_rejects_invalid_dynamic_job_details() -> None:
    with pytest.raises(ValueError, match="require a name"):
        JobListing(
            id="job-123",
            title="Automation Engineer",
            company="Example Co",
            source_url="https://example.com/jobs/job-description.185158.html",
            retrieval_mode="url",
            job_details={"dynamic_fields": [{"dynamic": True, "value": "Platform"}]},
        )


@pytest.mark.parametrize(
    "bad_job_id",
    ["../outside", "nested/job", "job\\nested", " job-123", ""],
)
def test_storage_backed_models_reject_path_like_job_ids(bad_job_id: str) -> None:
    with pytest.raises(ValueError, match="Job ID"):
        JobListing(
            id=bad_job_id,
            title="Automation Engineer",
            company="Example Co",
            source_url="https://example.com/jobs/job-description.185158.html",
            retrieval_mode="url",
        )

    with pytest.raises(ValueError, match="Job ID"):
        TrackerRecord(
            job_id=bad_job_id,
            title="Automation Engineer",
            company="Example Co",
            source_url="https://example.com/jobs/job-description.185158.html",
            retrieval_mode="url",
        )

    with pytest.raises(ValueError, match="Job ID"):
        ApplicationRequirements(
            job_id=bad_job_id,
            apply_url="https://example.com/apply/automation-engineer",
            source_url="https://example.com/jobs/job-description.185158.html",
        )

    with pytest.raises(ValueError, match="Job ID"):
        ApplicationPackage(job_id=bad_job_id)

    with pytest.raises(ValueError, match="Job ID"):
        ApplicationFillPlan(
            job_id=bad_job_id,
            apply_url="https://example.com/apply/automation-engineer",
        )


def test_application_package_round_trip() -> None:
    trace = AIWorkflowTrace(
        workflow_name="application_package",
        operation="AI package generation",
        model="gpt-5.4",
        profile_name="application_package",
        temperature=0.6,
        max_output_tokens=9000,
        timeout_seconds=90,
        max_retries=2,
        retry_backoff_seconds=[1.0, 2.0],
        attempt_count=2,
        duration_ms=321,
    )
    package = ApplicationPackage(
        job_id="job-123",
        status="draft",
        workflow_trace=trace,
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                required=True,
                status="needs_review",
                content="Dear hiring team...",
                source_prompt="Please upload a cover letter.",
                source_requirement="Cover letter required.",
                metadata={"language": "en"},
            )
        ],
        missing_information=["Confirm preferred location."],
        selected_experience_units=["exp-001"],
        generation_notes=["Generated from reviewed requirements."],
    )

    reloaded = ApplicationPackage.model_validate(package.model_dump(mode="json"))

    assert reloaded == package


def test_application_fill_plan_round_trip() -> None:
    fill_plan = ApplicationFillPlan(
        job_id="job-123",
        apply_url="https://example.com/apply/automation-engineer",
        review_status="reviewed",
        field_values=[
            ApplicationFillFieldValue(
                label="Vorname",
                value="Taylor",
                required=True,
                input_type="text",
                options=["Taylor"],
                source="candidate_profile.cv_extracted.identity.full_name",
                confidence="high",
            )
        ],
        upload_files=[
            ApplicationFillUploadFile(
                label="Lebenslauf",
                file_path="/tmp/candidate/cv.pdf",
                document_type="cv",
                required=True,
                source="candidate_profile.source_documents.cv.file_path",
                confidence="high",
            )
        ],
        needs_answer_fields=[
            ApplicationFillNeedsAnswerField(
                label="Earliest available start date",
                name="start_date",
                required=True,
                input_type="text",
                options=["Immediately", "After notice period"],
                reason="No safe candidate or reviewed package value is available.",
                source="application_requirements",
                confidence="medium",
            )
        ],
        blocked_fields=[
            ApplicationFillBlockedField(
                label="Privacy acknowledgement",
                reason="Consent requires user review.",
                required=True,
                input_type="checkbox",
                options=["true", "false"],
                source="application_requirements",
                confidence="high",
            )
        ],
        submit_guard_labels=["Weiter & Prüfen", "Submit"],
    )

    reloaded = ApplicationFillPlan.model_validate(fill_plan.model_dump(mode="json"))

    assert reloaded == fill_plan


def test_application_requirements_round_trip_includes_review_status() -> None:
    trace = AIWorkflowTrace(
        workflow_name="application_requirements",
        operation="AI application requirements extraction",
        model="gpt-5.4",
        profile_name="application_requirements",
        temperature=0.0,
        max_output_tokens=6000,
        timeout_seconds=60,
        max_retries=2,
        retry_backoff_seconds=[1.0, 2.0],
        attempt_count=1,
        duration_ms=210,
    )
    requirements = ApplicationRequirements(
        job_id="job-123",
        apply_url="https://example.com/apply/automation-engineer",
        source_url="https://example.com/jobs/automation-engineer",
        review_status="reviewed",
        status="discovered",
        job_preserving=True,
        workflow_trace=trace,
    )

    reloaded = ApplicationRequirements.model_validate(requirements.model_dump(mode="json"))

    assert reloaded == requirements
