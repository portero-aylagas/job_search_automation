from __future__ import annotations

from pathlib import Path

import pytest

from src.application_fill_plan import (
    ApplicationFieldMappingSuggestion,
    FillPlanTargetField,
    apply_fill_plan_edits,
    build_application_fill_plan_source_fingerprints,
    fill_plan_blocked_field_edit_key,
    fill_plan_field_edit_key,
    fill_plan_needs_answer_edit_key,
    fill_plan_upload_edit_key,
    generate_application_fill_plan,
    get_application_fill_plan_freshness_blockers,
    get_application_fill_plan_review_blockers,
    load_application_fill_plan,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.schemas import (
    ApplicationArtifact,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationPageControl,
    ApplicationPageFormSummary,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    CandidateOptionalDocument,
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
                        "first_name": "Taylor",
                        "last_name": "Rivera",
                        "gender": "Female",
                        "email": "taylor@example.com",
                        "phone": "+49 170 123456",
                        "location": "Berlin, Germany",
                        "street_address": "Example Street",
                        "street_number": "12",
                        "postal_code": "10115",
                        "city": "Berlin",
                        "country": "Deutschland",
                        "nationality": "Spanish",
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
            ApplicationFormField(label="Anrede", required=True, input_type="radio"),
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
            ApplicationFormField(
                label="Straße/Nr./Hausanschrift",
                required=False,
                input_type="text",
            ),
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
                label="Internal referral at Example Mobility GmbH",
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
                content="Berlin, Hamburg",
            )
        ],
    )


def make_page_snapshot() -> ApplicationPageSnapshot:
    return ApplicationPageSnapshot(
        requested_url="https://example.com/apply/automation-engineer",
        evidence_matches=["Anhang hochladen *"],
        controls=[
            ApplicationPageControl(
                name="first_name",
                label="Vorname",
                input_type="text",
                required=True,
                evidence="Vorname *",
            )
        ],
        forms=[
            ApplicationPageFormSummary(
                labels=["Datenschutzerklärung gelesen und verstanden"],
            )
        ],
        visible_text_excerpt=(
            "Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen "
            "und laden Sie Ihre Bewerbungsunterlagen hoch."
        ),
    )


def review_all_blocked_fields(fill_plan):
    blocked_values_by_key = {
        fill_plan_blocked_field_edit_key(field, index): "true" if field.required else ""
        for index, field in enumerate(fill_plan.blocked_fields)
    }
    return apply_fill_plan_edits(
        fill_plan,
        {},
        blocked_values_by_key=blocked_values_by_key,
    )


def test_fill_plan_file_saves_and_loads(tmp_path: Path) -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )
    reviewed_plan = mark_application_fill_plan_reviewed(
        review_all_blocked_fields(fill_plan)
    )

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

    assert values_by_label["Anrede"] == "Frau"
    assert values_by_label["Vorname"] == "Taylor"
    assert values_by_label["Nachname"] == "Rivera"
    assert values_by_label["E-Mail-Adresse"] == "taylor@example.com"
    assert values_by_label["Telefon"] == "+49170123456"
    assert values_by_label["Land Ihres Wohnsitzes"] == "Deutschland"
    assert values_by_label["Postleitzahl"] == "10115"
    assert values_by_label["Straße/Nr./Hausanschrift"] == "Example Street 12"


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


def test_required_cover_letter_becomes_generated_pdf_upload() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents = []
    requirements.motivation_letter = ApplicationRequirementFinding(
        label="Cover Letter / Anschreiben",
        required=True,
        evidence="Please upload a cover letter.",
        confidence="high",
    )
    package = make_package().model_copy(deep=True)
    package.artifacts.append(
        ApplicationArtifact(
            id="cover-letter-draft",
            type="cover_letter",
            label="Cover Letter Draft",
            content="Dear hiring team...",
            metadata={"generated_file_path": "/tmp/generated/cover_letter.pdf"},
        )
    )

    fill_plan = generate_application_fill_plan(make_profile(), requirements, package)

    assert len(fill_plan.upload_files) == 1
    upload = fill_plan.upload_files[0]
    assert upload.document_type == "cover_letter"
    assert upload.file_path == "/tmp/generated/cover_letter.pdf"
    assert upload.required is True


def test_fill_plan_includes_generated_and_uploaded_required_documents() -> None:
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.source_documents.optional_documents = [
        CandidateOptionalDocument(
            file_path="/tmp/candidate/certificate.pdf",
            file_name="certificate.pdf",
            document_type="certificate",
            parsed=True,
        ),
        CandidateOptionalDocument(
            file_path="/tmp/candidate/reference.pdf",
            file_name="reference.pdf",
            document_type="reference",
            parsed=True,
        ),
    ]
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents[0].constraints = [
        "Lebenslauf",
        "Zeugnisse",
        "Referenzen",
    ]
    requirements.motivation_letter = ApplicationRequirementFinding(
        label="Cover Letter / Anschreiben",
        required=True,
        evidence="Bitte Anschreiben hochladen.",
        confidence="high",
    )
    package = make_package().model_copy(deep=True)
    package.artifacts.append(
        ApplicationArtifact(
            id="cover-letter-draft",
            type="cover_letter",
            label="Cover Letter Draft",
            content="Sehr geehrtes Team...",
            metadata={"generated_file_path": "/tmp/generated/cover_letter.pdf"},
        )
    )

    fill_plan = generate_application_fill_plan(profile, requirements, package)

    uploads_by_type = {upload.document_type: upload for upload in fill_plan.upload_files}
    assert uploads_by_type["cv"].file_path == "/tmp/candidate/cv.pdf"
    assert uploads_by_type["certificate"].file_path == "/tmp/candidate/certificate.pdf"
    assert uploads_by_type["reference"].file_path == "/tmp/candidate/reference.pdf"
    assert uploads_by_type["cover_letter"].file_path == (
        "/tmp/generated/cover_letter.pdf"
    )
    assert uploads_by_type["cover_letter"].source == (
        "application_package.artifacts.cover-letter-draft.generated_file_path"
    )


def test_grouped_attachment_text_creates_separate_upload_rows() -> None:
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.source_documents.optional_documents = [
        CandidateOptionalDocument(
            file_path="/tmp/candidate/certificate.pdf",
            file_name="certificate.pdf",
            document_type="certificate",
            parsed=True,
        ),
        CandidateOptionalDocument(
            file_path="/tmp/candidate/reference.pdf",
            file_name="reference.pdf",
            document_type="reference",
            parsed=True,
        ),
    ]
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents = [
        ApplicationRequirementFinding(
            label="Attachments",
            required=True,
            evidence="Upload CV, cover letter, certificates, references.",
            confidence="high",
        )
    ]
    requirements.motivation_letter = None
    package = make_package().model_copy(deep=True)
    package.artifacts.append(
        ApplicationArtifact(
            id="cover-letter-draft",
            type="cover_letter",
            label="Cover Letter Draft",
            content="Dear hiring team...",
            metadata={"generated_file_path": "/tmp/generated/cover_letter.pdf"},
        )
    )

    fill_plan = generate_application_fill_plan(profile, requirements, package)

    uploads = [(upload.document_type, upload.file_path) for upload in fill_plan.upload_files]
    assert uploads == [
        ("cv", "/tmp/candidate/cv.pdf"),
        ("cover_letter", "/tmp/generated/cover_letter.pdf"),
        ("certificate", "/tmp/candidate/certificate.pdf"),
        ("reference", "/tmp/candidate/reference.pdf"),
    ]
    assert len({upload.label for upload in fill_plan.upload_files}) == 4


def test_optional_requested_document_without_uploaded_file_is_not_sent() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents = []
    requirements.upload_expectations = [
        ApplicationRequirementFinding(
            label="Additional certificates",
            required=False,
            evidence="You may upload certificates.",
            confidence="medium",
        )
    ]

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    assert fill_plan.upload_files == []
    reviewed_non_upload_blockers = review_all_blocked_fields(fill_plan)
    assert get_application_fill_plan_review_blockers(reviewed_non_upload_blockers) == []


def test_required_document_without_available_file_creates_upload_blocker() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents = [
        ApplicationRequirementFinding(
            label="Certificates",
            required=True,
            evidence="Certificates are required.",
            confidence="high",
        )
    ]

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    assert len(fill_plan.upload_files) == 1
    upload = fill_plan.upload_files[0]
    assert upload.document_type == "certificate"
    assert upload.file_path == ""
    assert upload.required is True
    assert upload.source == "missing_required_document"
    reviewed_non_upload_blockers = review_all_blocked_fields(fill_plan)
    assert get_application_fill_plan_review_blockers(reviewed_non_upload_blockers) == [
        "Provide file paths for required uploads: Certificates."
    ]


def test_unrequested_optional_documents_are_not_sent_to_browser() -> None:
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.source_documents.optional_documents = [
        CandidateOptionalDocument(
            file_path="/tmp/candidate/certificate.pdf",
            file_name="certificate.pdf",
            document_type="certificate",
            parsed=True,
        )
    ]

    fill_plan = generate_application_fill_plan(
        profile,
        make_requirements(),
        make_package(),
    )

    assert [(upload.document_type, upload.file_path) for upload in fill_plan.upload_files] == [
        ("cv", "/tmp/candidate/cv.pdf")
    ]


def test_fill_plan_preserves_discovered_field_options() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields[0].options = ["Frau", "Herr", "Divers"]

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    values_by_label = {field.label: field for field in fill_plan.field_values}

    assert values_by_label["Anrede"].options == ["Frau", "Herr", "Divers"]


def test_gender_maps_to_english_salutation_options() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields[0] = ApplicationFormField(
        label="Salutation",
        required=True,
        input_type="select",
        options=["Mr", "Ms"],
    )

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert values_by_label["Salutation"] == "Ms"


def test_diverse_gender_maps_to_german_anrede_option() -> None:
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.cv_extracted.identity.gender = "Diverse"
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields[0].options = ["Frau", "Herr", "Divers"]

    fill_plan = generate_application_fill_plan(
        profile,
        requirements,
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert values_by_label["Anrede"] == "Divers"


def test_diverse_gender_maps_to_english_salutation_option() -> None:
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.cv_extracted.identity.gender = "Diverse"
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields[0] = ApplicationFormField(
        label="Salutation",
        required=True,
        input_type="select",
        options=["Mr", "Ms", "Mx"],
    )

    fill_plan = generate_application_fill_plan(
        profile,
        requirements,
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert values_by_label["Salutation"] == "Mx"


def test_generic_title_field_is_not_filled_from_gender() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields[0] = ApplicationFormField(
        label="Title",
        required=False,
        input_type="text",
    )

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert "Title" not in values_by_label


def test_control_label_maps_to_fill_plan_field_evidence() -> None:
    requirements = make_requirements().model_copy(deep=True)
    for field in requirements.profile_fields:
        if field.label == "Vorname":
            field.name = "first_name"
            field.evidence = "Vorname *"

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
        page_snapshot=make_page_snapshot(),
    )

    values_by_label = {field.label: field for field in fill_plan.field_values}
    first_name = values_by_label["Vorname"]

    assert first_name.literal_evidence == ["Vorname"]
    assert first_name.evidence_source == "control_label"
    assert first_name.evidence_status == "literal_verified"


def test_form_label_maps_to_blocked_consent_gate_evidence() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
        page_snapshot=make_page_snapshot(),
    )

    blocked_by_label = {field.label: field for field in fill_plan.blocked_fields}
    privacy_gate = blocked_by_label["Privacy acknowledgement required to continue"]

    assert privacy_gate.literal_evidence == ["Datenschutzerklärung gelesen und verstanden"]
    assert privacy_gate.evidence_source == "form_label"
    assert privacy_gate.evidence_status == "literal_verified"


def test_evidence_match_snippets_are_attached_to_upload_and_consent_items() -> None:
    snapshot = ApplicationPageSnapshot(
        requested_url="https://example.com/apply/automation-engineer",
        evidence_matches=[
            "Anhang hochladen *",
            "Datenschutzerklärung gelesen und verstanden",
        ],
    )

    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
        page_snapshot=snapshot,
    )

    upload = fill_plan.upload_files[0]
    blocked_by_label = {field.label: field for field in fill_plan.blocked_fields}
    privacy_gate = blocked_by_label["Privacy acknowledgement required to continue"]

    assert upload.literal_evidence == ["Anhang hochladen *"]
    assert upload.evidence_source == "evidence_match"
    assert upload.evidence_status == "literal_verified"
    assert privacy_gate.literal_evidence == [
        "Datenschutzerklärung gelesen und verstanden"
    ]
    assert privacy_gate.evidence_source == "evidence_match"
    assert privacy_gate.evidence_status == "literal_verified"


def test_missing_literal_evidence_marks_item_interpreted_only() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
        page_snapshot=ApplicationPageSnapshot(
            requested_url="https://example.com/apply/automation-engineer",
        ),
    )

    values_by_label = {field.label: field for field in fill_plan.field_values}
    first_name = values_by_label["Vorname"]

    assert first_name.literal_evidence == []
    assert first_name.evidence_source == "interpreted_only"
    assert first_name.evidence_status == "interpreted_only"


def test_missing_values_and_sensitive_fields_are_blocked() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    blocked_by_label = {field.label: field.reason for field in fill_plan.blocked_fields}

    assert "Haben Sie eine anerkannte Schwerbehinderung?" in blocked_by_label
    assert "Internal referral at Example Mobility GmbH" in blocked_by_label
    assert "Privacy acknowledgement required to continue" in blocked_by_label
    assert "Haben Sie eine anerkannte Schwerbehinderung?" not in {
        field.label for field in fill_plan.needs_answer_fields
    }


def test_required_safe_missing_field_becomes_needs_answer() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Earliest available start date",
            required=True,
            input_type="text",
        )
    )

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    needs_by_label = {field.label: field for field in fill_plan.needs_answer_fields}
    blocked_by_label = {field.label for field in fill_plan.blocked_fields}

    assert "Earliest available start date" in needs_by_label
    assert needs_by_label["Earliest available start date"].required is True
    assert (
        needs_by_label["Earliest available start date"].reason
        == "No safe candidate or reviewed package value is available."
    )
    assert "Earliest available start date" not in blocked_by_label


def test_optional_safe_missing_field_does_not_block_review_plan() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Personal website",
            required=False,
            input_type="text",
        )
    )
    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.cv_extracted.identity.portfolio_url = ""

    fill_plan = generate_application_fill_plan(
        profile,
        requirements,
        make_package(),
    )

    blocked_by_label = {field.label: field.reason for field in fill_plan.blocked_fields}
    needs_answer_labels = {field.label for field in fill_plan.needs_answer_fields}

    assert "Personal website" in blocked_by_label
    assert "Optional field left empty" in blocked_by_label["Personal website"]
    assert "Personal website" not in needs_answer_labels


def test_needs_answer_field_preserves_evidence() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            name="earliest_start",
            label="Earliest available start date",
            required=True,
            input_type="text",
            evidence="Earliest available start date *",
        )
    )
    snapshot = ApplicationPageSnapshot(
        requested_url="https://example.com/apply/automation-engineer",
        controls=[
            ApplicationPageControl(
                name="earliest_start",
                label="Earliest available start date",
                input_type="text",
                required=True,
                evidence="Earliest available start date *",
            )
        ],
    )

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
        page_snapshot=snapshot,
    )

    needs_by_label = {field.label: field for field in fill_plan.needs_answer_fields}
    needs_answer = needs_by_label["Earliest available start date"]

    assert needs_answer.literal_evidence == ["Earliest available start date"]
    assert needs_answer.evidence_source == "control_label"
    assert needs_answer.evidence_status == "literal_verified"


def test_package_form_answer_artifacts_map_to_matching_questions() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert (
        values_by_label["Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"]
        == "Berlin, Hamburg"
    )


def test_semantic_mapper_can_fill_remaining_safe_fields() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Earliest available start date",
            required=False,
            input_type="text",
        )
    )

    def fake_mapper(
        _profile: CandidateProfile,
        _requirements: ApplicationRequirements,
        _package: ApplicationPackage,
        target_fields: list[FillPlanTargetField],
        resolved_fields: list[object],
    ) -> list[ApplicationFieldMappingSuggestion]:
        assert [field.label for field in target_fields] == ["Earliest available start date"]
        assert isinstance(resolved_fields, list)
        return [
            ApplicationFieldMappingSuggestion(
                label="Earliest available start date",
                value="Immediately",
                source="candidate_profile.candidate_preferences.availability",
                confidence="high",
            )
        ]

    profile = make_profile().model_copy(deep=True)
    profile.candidate_profile.candidate_preferences.availability = "Immediately"

    fill_plan = generate_application_fill_plan(
        profile,
        requirements,
        make_package(),
        semantic_mapper=fake_mapper,
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}

    assert values_by_label["Earliest available start date"] == "Immediately"


def test_mapper_can_skip_duplicate_of_existing_resolved_field() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Preferred work location",
            required=True,
            input_type="text",
        )
    )

    def duplicate_mapper(
        _profile: CandidateProfile,
        _requirements: ApplicationRequirements,
        _package: ApplicationPackage,
        target_fields: list[FillPlanTargetField],
        resolved_fields: list[object],
    ) -> list[ApplicationFieldMappingSuggestion]:
        assert [field.label for field in target_fields] == ["Preferred work location"]
        assert any(
            getattr(field, "label", "")
            == "Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"
            for field in resolved_fields
        )
        return [
            ApplicationFieldMappingSuggestion(
                label="Preferred work location",
                action="skip_duplicate",
                value="",
                reason="Already covered by the reviewed location preference field.",
            )
        ]

    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
        semantic_mapper=duplicate_mapper,
    )

    values_by_label = {field.label: field.value for field in fill_plan.field_values}
    blocked_by_label = {field.label: field.reason for field in fill_plan.blocked_fields}

    assert "Preferred work location" not in values_by_label
    assert (
        blocked_by_label["Preferred work location"]
        == "Already covered by the reviewed location preference field."
    )
    assert (
        values_by_label["Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"]
        == "Berlin, Hamburg"
    )


def test_apply_fill_plan_edits_updates_fields_and_upload_path() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )
    field_keys = {
        field.label: fill_plan_field_edit_key(field, index)
        for index, field in enumerate(fill_plan.field_values)
    }
    upload_keys = {
        upload.label: fill_plan_upload_edit_key(upload, index)
        for index, upload in enumerate(fill_plan.upload_files)
    }

    edited = apply_fill_plan_edits(
        fill_plan,
        {
            field_keys["Vorname"]: "Jordan",
            field_keys[
                "Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"
            ]: "Berlin",
        },
        upload_paths_by_key={
            upload_keys["Application attachments / Bewerbungsunterlagen"]: "/tmp/updated.pdf"
        },
    )

    values_by_label = {field.label: field.value for field in edited.field_values}

    assert edited.review_status == "draft"
    assert values_by_label["Vorname"] == "Jordan"
    assert (
        values_by_label["Bitte wählen Sie alle Standorte aus, die für Sie in Frage kommen"]
        == "Berlin"
    )
    assert values_by_label["Anrede"] == "Frau"
    first_name = next(field for field in edited.field_values if field.label == "Vorname")
    assert first_name.source == "manual_review"
    assert edited.upload_files[0].file_path == "/tmp/updated.pdf"
    assert edited.upload_files[0].source == "manual_review"


def test_apply_fill_plan_edits_promotes_needs_answer_to_field_value() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Earliest available start date",
            required=True,
            input_type="text",
        )
    )
    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )
    needs_answer_key = fill_plan_needs_answer_edit_key(
        fill_plan.needs_answer_fields[0],
        0,
    )

    edited = apply_fill_plan_edits(
        fill_plan,
        {},
        needs_answer_values_by_key={needs_answer_key: "Immediately"},
    )

    values_by_label = {field.label: field for field in edited.field_values}

    assert edited.needs_answer_fields == []
    assert values_by_label["Earliest available start date"].value == "Immediately"
    assert values_by_label["Earliest available start date"].source == "manual_review"


def test_apply_fill_plan_edits_promotes_required_blank_and_blocks_review() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Earliest available start date",
            required=True,
            input_type="text",
        )
    )
    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )
    needs_answer_key = fill_plan_needs_answer_edit_key(
        fill_plan.needs_answer_fields[0],
        0,
    )

    edited = apply_fill_plan_edits(
        fill_plan,
        {},
        needs_answer_values_by_key={needs_answer_key: ""},
    )

    values_by_label = {field.label: field for field in edited.field_values}

    assert edited.needs_answer_fields == []
    assert values_by_label["Earliest available start date"].value == ""
    assert (
        "Provide values for required fields: Earliest available start date."
        in get_application_fill_plan_review_blockers(edited)
    )


def test_apply_fill_plan_edits_promotes_blocked_field_to_field_value() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )
    blocked_keys = {
        field.label: fill_plan_blocked_field_edit_key(field, index)
        for index, field in enumerate(fill_plan.blocked_fields)
    }

    edited = apply_fill_plan_edits(
        fill_plan,
        {},
        blocked_values_by_key={
            blocked_keys["Internal referral at Example Mobility GmbH"]: ""
        },
    )

    values_by_label = {field.label: field for field in edited.field_values}
    blocked_labels = {field.label for field in edited.blocked_fields}
    promoted = values_by_label["Internal referral at Example Mobility GmbH"]

    assert promoted.value == ""
    assert promoted.source == "manual_review"
    assert promoted.required is False
    assert "Internal referral at Example Mobility GmbH" not in blocked_labels


def test_required_blocked_consent_can_be_reviewed_as_true() -> None:
    fill_plan = generate_application_fill_plan(
        make_profile(),
        make_requirements(),
        make_package(),
    )
    blocked_keys = {
        field.label: fill_plan_blocked_field_edit_key(field, index)
        for index, field in enumerate(fill_plan.blocked_fields)
    }

    edited = apply_fill_plan_edits(
        fill_plan,
        {},
        blocked_values_by_key={
            blocked_keys["Privacy acknowledgement required to continue"]: "true"
        },
    )

    values_by_label = {field.label: field for field in edited.field_values}
    consent = values_by_label["Privacy acknowledgement required to continue"]

    assert consent.value == "true"
    assert consent.input_type == "checkbox"
    assert consent.options == ["true", "false"]
    assert consent.required is True


def test_mark_fill_plan_reviewed_blocks_unresolved_needs_answer_fields() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.profile_fields.append(
        ApplicationFormField(
            label="Earliest available start date",
            required=True,
            input_type="text",
        )
    )
    fill_plan = generate_application_fill_plan(
        make_profile(),
        requirements,
        make_package(),
    )

    with pytest.raises(ValueError, match="Save reviewed values"):
        mark_application_fill_plan_reviewed(fill_plan)


def test_reviewed_fill_plan_becomes_stale_when_package_gains_generated_file_path() -> None:
    requirements = make_requirements().model_copy(deep=True)
    requirements.required_documents = []
    requirements.motivation_letter = ApplicationRequirementFinding(
        label="Optional cover letter",
        required=False,
        evidence="You may upload a cover letter.",
        confidence="medium",
    )
    package = make_package().model_copy(deep=True)
    package.artifacts.append(
        ApplicationArtifact(
            id="cover-letter-draft",
            type="cover_letter",
            label="Cover Letter Draft",
            content="Dear hiring team...",
        )
    )
    fill_plan = mark_application_fill_plan_reviewed(
        review_all_blocked_fields(
            generate_application_fill_plan(make_profile(), requirements, package)
        )
    )
    package.artifacts[-1].metadata["generated_file_path"] = (
        "/tmp/generated/cover_letter.pdf"
    )

    blockers = get_application_fill_plan_freshness_blockers(
        fill_plan,
        make_profile(),
        requirements,
        package,
    )

    assert blockers == [
        "Refresh the application fill plan because application package upload "
        "artifacts changed since review."
    ]


def test_reviewed_fill_plan_becomes_stale_when_optional_documents_change() -> None:
    profile = make_profile()
    fill_plan = mark_application_fill_plan_reviewed(
        review_all_blocked_fields(
            generate_application_fill_plan(profile, make_requirements(), make_package())
        )
    )
    changed_profile = profile.model_copy(deep=True)
    changed_profile.candidate_profile.source_documents.optional_documents.append(
        CandidateOptionalDocument(
            file_path="/tmp/candidate/reference.pdf",
            file_name="reference.pdf",
            document_type="reference",
            parsed=True,
        )
    )

    blockers = get_application_fill_plan_freshness_blockers(
        fill_plan,
        changed_profile,
        make_requirements(),
        make_package(),
    )

    assert blockers == [
        "Refresh the application fill plan because candidate profile documents "
        "changed since review."
    ]


def test_refreshed_fill_plan_matches_current_source_fingerprints() -> None:
    profile = make_profile()
    requirements = make_requirements()
    package = make_package()
    fill_plan = generate_application_fill_plan(profile, requirements, package)

    assert fill_plan.source_fingerprints == build_application_fill_plan_source_fingerprints(
        profile,
        requirements,
        package,
    )
    assert (
        get_application_fill_plan_freshness_blockers(
            fill_plan,
            profile,
            requirements,
            package,
        )
        == []
    )
