from __future__ import annotations

from pathlib import Path

from src.application_fill_plan import (
    generate_application_fill_plan,
    load_application_fill_plan,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.schemas import (
    ApplicationArtifact,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    CandidateProfile,
)


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {
                        "file_path": "/tmp/candidate/cv.pdf",
                        "parsed": True,
                    }
                },
                "cv_extracted": {
                    "identity": {
                        "full_name": "Taylor Rivera",
                        "email": "taylor@example.com",
                        "phone": "+49 170 123456",
                        "location": "Berlin, Germany",
                        "linkedin_url": "https://linkedin.com/in/taylor-rivera",
                        "github_url": "https://github.com/taylor-rivera",
                        "portfolio_url": "https://taylor.example.com",
                    }
                },
            }
        }
    )


def make_requirements() -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id="job-123",
        apply_url="https://example.com/apply/automation-engineer",
        source_url="https://example.com/jobs/automation-engineer",
        status="discovered",
        review_status="reviewed",
        job_preserving=True,
        required_documents=[
            ApplicationRequirementFinding(
                label="Application attachments / Bewerbungsunterlagen",
                required=True,
                evidence="Anhang hochladen *",
                confidence="high",
                constraints=["Lebenslauf"],
            )
        ],
        profile_fields=[
            ApplicationFormField(label="Vorname", required=True, input_type="text"),
            ApplicationFormField(label="Nachname", required=True, input_type="text"),
            ApplicationFormField(label="E-Mail-Adresse", required=True, input_type="text"),
            ApplicationFormField(label="Telefon", required=False, input_type="text"),
            ApplicationFormField(
                label="Land Ihres Wohnsitzes",
                required=False,
                input_type="select",
            ),
            ApplicationFormField(label="Postleitzahl", required=True, input_type="text"),
        ],
        screening_questions=[
            ApplicationScreeningQuestion(
                question="Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen",
                required=True,
                input_type="checkbox",
            ),
            ApplicationScreeningQuestion(
                question="Haben Sie eine anerkannte Schwerbehinderung?",
                required=False,
                input_type="checkbox",
            ),
        ],
        custom_form_fields=[
            ApplicationFormField(
                label="Empfehlung durch eine/n Mitarbeiter/in von tracetronic GmbH",
                required=False,
                input_type="text",
            )
        ],
        consent_requirements=[
            ApplicationRequirementFinding(
                label="Privacy acknowledgement required to continue",
                required=True,
                evidence="Datenschutzerklärung gelesen und verstanden",
                confidence="high",
            )
        ],
    )


def make_package() -> ApplicationPackage:
    return ApplicationPackage(
        job_id="job-123",
        status="draft",
        artifacts=[
            ApplicationArtifact(
                id="locations-answer",
                type="form_answer",
                label="Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen",
                required=True,
                content="Dresden, München",
            )
        ],
    )


def test_fill_plan_file_saves_and_loads(tmp_path: Path) -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )
    reviewed_plan = mark_application_fill_plan_reviewed(fill_plan)

    saved_path = save_application_fill_plan(tmp_path, reviewed_plan)
    loaded_plan = load_application_fill_plan(tmp_path, "job-123")

    assert saved_path.name == "application_fill_plan.json"
    assert loaded_plan == reviewed_plan


def test_candidate_identity_maps_to_profile_fields() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert values_by_label["Vorname"] == "Taylor"
    assert values_by_label["Nachname"] == "Rivera"
    assert values_by_label["E-Mail-Adresse"] == "taylor@example.com"
    assert values_by_label["Telefon"] == "+49 170 123456"
    assert values_by_label["Land Ihres Wohnsitzes"] == "Deutschland"


def test_cv_becomes_allowed_upload() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    assert len(fill_plan.upload_files) == 1
    upload = fill_plan.upload_files[0]
    assert upload.file_path == "/tmp/candidate/cv.pdf"
    assert upload.document_type == "cv"
    assert upload.required is True


def test_missing_values_and_sensitive_fields_are_blocked() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    blocked_by_label = {field.label: field.reason for field in fill_plan.blocked_fields}

    assert "Postleitzahl" in blocked_by_label
    assert "Haben Sie eine anerkannte Schwerbehinderung?" in blocked_by_label
    assert "Empfehlung durch eine/n Mitarbeiter/in von tracetronic GmbH" in blocked_by_label
    assert "Privacy acknowledgement required to continue" in blocked_by_label


def test_package_form_answer_artifacts_map_to_matching_questions() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert (
        values_by_label["Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"]
        == "Dresden, München"
    )
