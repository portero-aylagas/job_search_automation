from src.schemas import CandidatePreferences, CandidateProfile, TrackerRecord


def test_candidate_profile_round_trip() -> None:
    profile = CandidateProfile(
        candidate_profile={
            "profile_status": "draft",
            "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
            "cv_extracted": {
                "identity": {
                    "full_name": "Taylor Rivera",
                    "email": "taylor@example.com",
                    "phone": "+49 123 456",
                    "location": "Remote",
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
