from __future__ import annotations

from pathlib import Path

from src.job_intake import create_job_listing, persist_job_listing
from src.match_analysis import (
    analyze_match,
    load_match_analysis,
    match_analysis_is_fresh,
    review_match_analysis,
    save_match_analysis,
)
from src.schemas import CandidateProfile, ExperienceUnit, TrackerRecord
from src.storage import load_model


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
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
                    "skills": ["Python", "SQL", "Streamlit", "APIs"],
                    "work_experience": ["Built Python automation and SQL reporting tools."],
                },
                "candidate_preferences": {
                    "target_roles": ["Automation Engineer"],
                    "target_locations": ["Berlin", "Remote"],
                    "remote_preference": ["remote", "hybrid"],
                    "employment_type": ["full_time"],
                    "seniority_level": ["mid_level"],
                    "availability": "Immediately",
                    "salary_min_eur": 55000,
                    "salary_max_eur": 70000,
                    "work_authorization": "eu_authorized",
                },
            }
        }
    )


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        location="Berlin",
        remote_policy="Hybrid",
        description="Build workflow automation tools and dashboards.",
        requirements=["Python", "SQL", "Workflow automation", "Kubernetes"],
        nice_to_have_skills=["Streamlit"],
    )


def test_match_analysis_scores_skills_and_evidence() -> None:
    job = make_job()
    profile = make_profile()
    units = [
        ExperienceUnit(
            id="exp-1",
            title="Automation Analyst",
            organization="Ops Co",
            date_range="2024-2026",
            summary="Built Python automation for operations.",
            skills=["Python", "SQL", "Workflow automation"],
        )
    ]

    analysis = analyze_match(profile, job, units)

    assert analysis.job_id == job.id
    assert analysis.review_status == "draft"
    assert analysis.match_score > 70
    assert "Python" in analysis.matched_skills
    assert "Kubernetes" in analysis.missing_skills
    assert analysis.strong_experience_units == ["exp-1"]
    assert analysis.relevant_evidence[0].startswith("Automation Analyst:")


def test_match_analysis_review_updates_tracker_status(tmp_path: Path) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)
    analysis = analyze_match(make_profile(), job, [])
    save_match_analysis(tmp_path, analysis)

    reviewed = review_match_analysis(tmp_path, analysis, accepted=True)

    assert reviewed.review_status == "reviewed"
    tracker = load_model(
        tmp_path / "data" / "runtime" / "jobs.json",
        list[TrackerRecord],
        default=[],
    )
    assert tracker[0].status == "analyzed"
    assert tracker[0].match_score == reviewed.match_score
    assert load_match_analysis(tmp_path, job.id).review_status == "reviewed"


def test_rejected_match_updates_tracker_without_analyzed_status(tmp_path: Path) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)
    analysis = analyze_match(make_profile(), job, [])

    rejected = review_match_analysis(tmp_path, analysis, accepted=False)

    tracker = load_model(
        tmp_path / "data" / "runtime" / "jobs.json",
        list[TrackerRecord],
        default=[],
    )
    assert rejected.review_status == "rejected"
    assert tracker[0].status == "rejected_by_user"


def test_match_analysis_freshness_detects_changed_job() -> None:
    profile = make_profile()
    job = make_job()
    analysis = analyze_match(profile, job, [])

    assert match_analysis_is_fresh(analysis, profile, job, [])

    changed_job = job.model_copy(update={"requirements": [*job.requirements, "Docker"]})

    assert not match_analysis_is_fresh(analysis, profile, changed_job, [])
