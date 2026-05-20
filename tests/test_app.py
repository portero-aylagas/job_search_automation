import importlib
from pathlib import Path

from src.job_intake import create_job_listing
from src.llm_job_extraction import ApplyUrlResolution, RejectedApplyCandidate
from src.schemas import ApplicationRequirements, CandidateProfile


def test_app_module_imports() -> None:
    module = importlib.import_module("app")

    assert module is not None


def test_validate_candidate_profile_reports_missing_required_fields() -> None:
    app = importlib.import_module("app")

    errors = app.validate_candidate_profile(CandidateProfile())

    assert "Upload CV" in errors
    assert "Full name" in errors
    assert "Email" in errors
    assert "Target roles" in errors
    assert "Remote preference" in errors
    assert "Career level" in errors
    assert "Work authorization" in errors
    assert "Salary min" in errors
    assert "Salary max" in errors


def test_validate_candidate_profile_rejects_inverted_salary_range() -> None:
    app = importlib.import_module("app")
    profile = CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
                "cv_extracted": {
                    "identity": {"full_name": "Taylor Rivera", "email": "taylor@example.com"},
                },
                "candidate_preferences": {
                    "target_roles": ["Automation Engineer"],
                    "target_locations": ["Remote"],
                    "remote_preference": ["remote"],
                    "employment_type": ["full_time"],
                    "seniority_level": ["junior"],
                    "availability": "Immediately",
                    "salary_min_eur": 70000,
                    "salary_max_eur": 60000,
                    "work_authorization": "eu_authorized",
                },
            }
        }
    )

    errors = app.validate_candidate_profile(profile)

    assert "Salary max must be >= Salary min" in errors


def test_get_latest_candidate_profile_uses_current_draft(monkeypatch) -> None:
    app = importlib.import_module("app")
    current_draft = make_complete_candidate_profile().model_dump(mode="json")
    current_draft["candidate_profile"]["candidate_preferences"]["availability"] = (
        "Available next month"
    )
    monkeypatch.setattr(app, "get_candidate_profile_draft", lambda _base_dir: current_draft)

    profile = app.get_latest_candidate_profile(Path("/tmp"))

    assert profile.candidate_profile.candidate_preferences.availability == "Available next month"


def make_complete_candidate_profile(*, cv_parsed: bool = True) -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {"file_path": "/tmp/cv.pdf", "parsed": cv_parsed},
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


def make_package_job(*, description: str = "Build automation workflows."):
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        description=description,
    )


def make_package_requirements(job, *, status: str = "discovered", job_preserving: bool = True):
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=job.apply_url,
        source_url=job.source_url,
        status=status,
        job_preserving=job_preserving,
    )


def test_package_generation_blockers_require_parsed_job_description() -> None:
    app = importlib.import_module("app")
    job = make_package_job(description="")

    blockers = app.get_application_package_blockers(
        make_complete_candidate_profile(),
        job,
        make_package_requirements(job),
    )

    assert "Parse and save the job description" in " ".join(blockers)


def test_package_generation_blockers_require_parsed_cv() -> None:
    app = importlib.import_module("app")
    job = make_package_job()

    blockers = app.get_application_package_blockers(
        make_complete_candidate_profile(cv_parsed=False),
        job,
        make_package_requirements(job),
    )

    assert "Parse the candidate CV" in " ".join(blockers)


def test_package_generation_blockers_require_mandatory_candidate_fields() -> None:
    app = importlib.import_module("app")
    job = make_package_job()

    blockers = app.get_application_package_blockers(
        CandidateProfile(),
        job,
        make_package_requirements(job),
    )

    assert any(blocker.startswith("Complete the candidate profile") for blocker in blockers)


def test_package_generation_blockers_require_application_requirements() -> None:
    app = importlib.import_module("app")

    blockers = app.get_application_package_blockers(
        make_complete_candidate_profile(),
        make_package_job(),
        None,
    )

    assert "Discover application requirements" in " ".join(blockers)


def test_package_generation_blockers_reject_blocked_or_non_preserving_requirements() -> None:
    app = importlib.import_module("app")
    job = make_package_job()

    blocked_status = app.get_application_package_blockers(
        make_complete_candidate_profile(),
        job,
        make_package_requirements(job, status="blocked", job_preserving=False),
    )
    non_preserving = app.get_application_package_blockers(
        make_complete_candidate_profile(),
        job,
        make_package_requirements(job, job_preserving=False),
    )

    assert "Resolve application requirements" in " ".join(blocked_status)
    assert "Resolve application requirements" in " ".join(non_preserving)


def test_package_generation_has_no_blockers_when_prerequisites_are_complete() -> None:
    app = importlib.import_module("app")
    job = make_package_job()

    blockers = app.get_application_package_blockers(
        make_complete_candidate_profile(),
        job,
        make_package_requirements(job),
    )

    assert blockers == []


def test_resolved_apply_url_uses_only_resolved_valid_resolution() -> None:
    app = importlib.import_module("app")
    source_url = "https://example.com/jobs/automation-engineer"

    resolved = ApplyUrlResolution(
        status="resolved",
        apply_url="https://example.com/apply/automation-engineer",
        evidence=["Destination preserves Automation Engineer."],
        confidence="high",
    )
    needs_review = ApplyUrlResolution(
        status="needs_review",
        apply_url="https://example.com/apply/automation-engineer",
        notes="Could not verify job identity.",
    )

    assert app.resolved_apply_url(source_url, resolved) == (
        "https://example.com/apply/automation-engineer"
    )
    assert app.resolved_apply_url(source_url, needs_review) == ""
    assert app.resolved_apply_url(source_url, None) == ""


def test_validate_reviewed_apply_url_accepts_manual_unverified_values() -> None:
    app = importlib.import_module("app")
    source_url = "https://example.com/jobs/automation-engineer"
    needs_review = ApplyUrlResolution(
        status="needs_review",
        apply_url="https://example.com/apply/automation-engineer",
    )

    app.validate_reviewed_apply_url(
        "https://example.com/apply/automation-engineer",
        source_url,
        needs_review,
    )
    app.validate_reviewed_apply_url(
        "https://example.com/apply/automation-engineer",
        source_url,
        None,
    )


def test_validate_reviewed_apply_url_rejects_changed_verified_values() -> None:
    app = importlib.import_module("app")
    source_url = "https://example.com/jobs/automation-engineer"
    resolution = ApplyUrlResolution(
        status="resolved",
        apply_url="https://example.com/apply/automation-engineer",
    )

    app.validate_reviewed_apply_url(
        "https://example.com/apply/automation-engineer",
        source_url,
        resolution,
    )

    try:
        app.validate_reviewed_apply_url(
            "https://example.com/apply/different-job",
            source_url,
            resolution,
        )
    except ValueError as exc:
        assert "must match the verified" in str(exc)
    else:
        raise AssertionError("Changed apply URL should be rejected.")


def test_apply_resolution_details_preserves_evidence_and_rejections() -> None:
    app = importlib.import_module("app")
    resolution = ApplyUrlResolution(
        status="resolved",
        apply_url="https://example.com/apply/automation-engineer",
        notes="Verified final destination.",
        evidence=["Same title on destination page."],
        rejected_candidates=[
            RejectedApplyCandidate(
                url="https://example.com/careers",
                reason="Generic career page",
                evidence="Search all jobs",
            )
        ],
        confidence="high",
    )

    details = app.apply_resolution_details(
        "https://example.com/apply/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        resolution,
    )

    assert details["status"] == "resolved"
    assert details["confidence"] == "high"
    assert details["verified_by_resolver"] is True
    assert details["manual_override"] is False
    assert details["evidence"] == ["Same title on destination page."]
    assert details["rejected_candidates"][0]["reason"] == "Generic career page"


def test_apply_resolution_details_marks_manual_override() -> None:
    app = importlib.import_module("app")
    source_url = "https://example.com/jobs/automation-engineer"
    manual_url = "https://example.com/apply/automation-engineer"
    resolution = ApplyUrlResolution(
        status="needs_review",
        apply_url="",
        notes="Could not verify job identity.",
        confidence="low",
    )

    details = app.apply_resolution_details(manual_url, source_url, resolution)

    assert details["status"] == "needs_review"
    assert details["verified_by_resolver"] is False
    assert details["manual_override"] is True
    assert details["manual_apply_url"] == manual_url


def test_apply_resolution_details_handles_missing_resolution_as_manual_review() -> None:
    app = importlib.import_module("app")
    manual_url = "https://example.com/apply/automation-engineer"

    details = app.apply_resolution_details(
        manual_url,
        "https://example.com/jobs/automation-engineer",
        None,
    )

    assert details["status"] == "manual_review"
    assert details["apply_url"] == manual_url
    assert details["verified_by_resolver"] is False
    assert details["manual_override"] is True


def test_apply_url_review_messages_are_empty_when_final_apply_url_is_verified() -> None:
    app = importlib.import_module("app")

    messages = app.apply_url_review_messages(
        "https://example.com/jobs/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        "https://example.com/apply/automation-engineer",
    )

    assert messages == {"errors": [], "warnings": [], "info": []}


def test_apply_url_review_messages_explain_manual_fallback_when_unverified() -> None:
    app = importlib.import_module("app")

    messages = app.apply_url_review_messages(
        "https://example.com/jobs/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        "",
    )

    assert any("application destination" in message for message in messages["errors"])
    assert messages["warnings"] == [
        "The extracted apply URL was not verified by the apply-link resolver."
    ]
    assert any("paste the application URL manually" in message for message in messages["info"])


def test_candidate_preferences_migrates_legacy_entry_level_employment_types() -> None:
    from src.schemas import CandidatePreferences

    preferences = CandidatePreferences.model_validate(
        {
            "target_roles": ["Automation Engineer"],
            "target_locations": ["Remote"],
            "remote_preference": ["remote"],
            "employment_type": ["full_time", "trainee", "working_student"],
            "seniority_level": ["junior"],
            "availability": "Immediately",
            "salary_min_eur": 55000,
            "salary_max_eur": 65000,
            "work_authorization": "eu_authorized",
        }
    )

    assert preferences.employment_type == ["full_time"]
    assert preferences.seniority_level == ["junior", "trainee", "working_student"]


def test_career_level_options_are_flat_and_unique() -> None:
    app = importlib.import_module("app")

    option_values = [value for value, _ in app.CAREER_LEVEL_OPTIONS]
    option_labels = [label for _, label in app.CAREER_LEVEL_OPTIONS]

    assert not hasattr(app, "SENIORITY_GROUPS")
    assert len(option_values) == len(set(option_values))
    assert len(option_labels) == len(set(option_labels))


def test_employment_type_labels_are_not_grouped() -> None:
    app = importlib.import_module("app")

    assert not hasattr(app, "EMPLOYMENT_TYPE_GROUPS")
    assert [label for _, label in app.EMPLOYMENT_TYPE_OPTIONS] == [
        "Full-time",
        "Part-time",
        "Contract",
        "Freelance",
    ]


def test_salary_labels_and_defaults_are_annual() -> None:
    app = importlib.import_module("app")

    assert "EUR / year" in app.required_label("Salary min (EUR / year)")
    assert "EUR / year" in app.required_label("Salary max (EUR / year)")


def test_optional_document_upload_menus_match_supported_categories() -> None:
    app = importlib.import_module("app")

    assert app.OPTIONAL_DOCUMENT_UPLOAD_MENUS == [
        ("reference", "Upload references"),
        ("certificate", "Upload certificates"),
        ("other", "Upload other documents"),
    ]
    assert set(app.OPTIONAL_DOCUMENT_TYPES) == {
        document_type for document_type, _ in app.OPTIONAL_DOCUMENT_UPLOAD_MENUS
    }


def test_merge_supplemental_extracted_data_appends_unique_items() -> None:
    app = importlib.import_module("app")
    from src.schemas import CandidateCVExtracted, CandidateSupplementalExtracted

    target = CandidateCVExtracted(
        skills=["Python"],
        certifications=["Cloud Fundamentals"],
    )
    supplemental = CandidateSupplementalExtracted(
        skills=["python", "SQL"],
        certifications=["Cloud Fundamentals", "Security Basics"],
        references=["Reference letter from Example Manager"],
    )

    app.merge_supplemental_extracted_data(target, supplemental)

    assert target.skills == ["Python", "SQL"]
    assert target.certifications == ["Cloud Fundamentals", "Security Basics"]
    assert target.references == ["Reference letter from Example Manager"]
