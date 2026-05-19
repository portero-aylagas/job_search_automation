import importlib

from src.schemas import CandidateProfile


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


def test_salary_labels_and_defaults_are_annual() -> None:
    app = importlib.import_module("app")

    assert "EUR / year" in app.required_label("Salary min (EUR / year)")
    assert "EUR / year" in app.required_label("Salary max (EUR / year)")
