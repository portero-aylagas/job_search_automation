from src.schemas import CandidateProfile, TrackerRecord


def test_candidate_profile_round_trip() -> None:
    profile = CandidateProfile(
        id="candidate-123",
        full_name="Taylor Rivera",
        professional_summary="Builds practical automation workflows.",
        target_roles=["Automation Engineer"],
        target_locations=["Remote"],
        skills=["Python", "APIs"],
        languages=["English"],
        salary_expectation="EUR 60000",
        constraints=["Remote only"],
        documents_used=["cv.pdf"],
    )

    reloaded = CandidateProfile.model_validate(profile.model_dump(mode="json"))

    assert reloaded == profile


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
