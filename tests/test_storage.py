from pathlib import Path

from src.schemas import CandidateProfile
from src.storage import load_json, load_model, save_json, save_model


def test_save_and_load_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "payload.json"
    payload = {"name": "Alex", "skills": ["Python", "SQL"]}

    save_json(target, payload)

    assert load_json(target) == payload


def test_load_json_returns_default_for_missing_file(tmp_path: Path) -> None:
    default_payload = {"status": "missing"}

    loaded = load_json(tmp_path / "missing.json", default=default_payload)

    assert loaded is default_payload


def test_save_model_creates_parent_directories_and_loads_model(tmp_path: Path) -> None:
    profile = CandidateProfile(
        candidate_profile={
            "profile_status": "draft",
            "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
            "cv_extracted": {
                "identity": {
                    "full_name": "Alex Mercer",
                    "email": "alex@example.com",
                    "phone": "",
                    "location": "Remote",
                    "linkedin_url": "",
                    "github_url": "",
                    "portfolio_url": "",
                },
                "work_experience": ["Automation specialist at Example Co"],
                "education": ["BSc Computer Science"],
                "skills": ["Python"],
                "languages": ["English"],
                "certifications": [],
                "projects": [],
            },
            "candidate_preferences": {
                "target_roles": ["Python Developer"],
                "target_locations": ["Remote"],
                "remote_preference": ["remote"],
                "employment_type": ["full_time"],
                "seniority_level": ["junior"],
                "availability": "Immediately",
                "salary_min_eur": 55000,
                "salary_max_eur": 65000,
                "work_authorization": "eu_authorized",
            },
        },
    )
    target = tmp_path / "deep" / "profile.json"

    save_model(target, profile)
    loaded = load_model(target, CandidateProfile)

    assert target.exists()
    assert loaded == profile
