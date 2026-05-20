from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application_package import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME,
    LLMApplicationArtifact,
    LLMApplicationPackageResponse,
    build_application_artifact_manifest,
    build_missing_information_defaults,
    generate_application_package,
    generate_application_package_with_llm,
    load_application_package,
    render_application_package_markdown,
    save_application_package,
    update_tracker_for_application_package,
)
from src.job_intake import create_job_listing
from src.sample_data import get_sample_candidate_profile, get_sample_experience_units
from src.schemas import (
    ApplicationArtifact,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    TrackerRecord,
)
from src.storage import load_model, save_model


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        requirements=["Python", "Test automation"],
    )


def make_requirements(job) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=job.apply_url,
        source_url=job.source_url,
        status="discovered",
        job_preserving=True,
        required_documents=[
            ApplicationRequirementFinding(
                label="CV and references",
                required=True,
                evidence="Upload CV and references.",
                confidence="high",
            )
        ],
        upload_expectations=[
            ApplicationRequirementFinding(
                label="Combined PDF",
                required=False,
                evidence="Prefer one combined PDF.",
                confidence="high",
                constraints=["5 MB per file", "20 MB total"],
            )
        ],
        screening_questions=[
            ApplicationScreeningQuestion(
                question="Which locations are suitable for you?",
                required=True,
                input_type="checkbox group",
                evidence="Select all suitable locations.",
                confidence="high",
            ),
            ApplicationScreeningQuestion(
                question="Do you have a severe disability you want to disclose?",
                required=False,
                input_type="checkbox",
                evidence="Disclosure question.",
                confidence="high",
            ),
        ],
        custom_form_fields=[
            ApplicationFormField(
                name="referral_code",
                label="Recommendation code",
                required=False,
                input_type="text",
                evidence="Enter recommendation code.",
                confidence="medium",
            ),
            ApplicationFormField(
                name="portfolio",
                label="Portfolio URL",
                required=False,
                input_type="text",
                evidence="Portfolio URL.",
                confidence="medium",
            ),
        ],
        motivation_letter=ApplicationRequirementFinding(
            label="Cover letter",
            required=True,
            evidence="Please upload a cover letter.",
            confidence="high",
        ),
        consent_requirements=[
            ApplicationRequirementFinding(
                label="Privacy consent",
                required=True,
                evidence="Confirm privacy policy.",
                confidence="high",
            )
        ],
        missing_or_uncertain=["Later application steps may ask for more details."],
        confidence="high",
    )


def find_property_schema(schema: dict, property_name: str) -> dict | None:
    properties = schema.get("properties", {})
    if property_name in properties:
        return properties[property_name]
    for definition in schema.get("$defs", {}).values():
        found = find_property_schema(definition, property_name)
        if found is not None:
            return found
    return None


def test_llm_application_package_schema_has_no_free_form_metadata() -> None:
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(LLMApplicationPackageResponse)

    assert find_property_schema(schema, "metadata") is None


def test_generate_application_package_with_llm_uses_creative_package_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job()
    parse_calls = []
    parsed_payload = LLMApplicationPackageResponse(
        job_id="wrong-job",
        artifacts=[
            LLMApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Application Summary",
                required=True,
                content="Strong automation fit.",
            )
        ],
        selected_experience_units=["exp-001"],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    package = generate_application_package_with_llm(
        get_sample_candidate_profile(),
        get_sample_experience_units(),
        job,
        None,
    )

    assert package.job_id == job.id
    assert package.artifacts[0].content == "Strong automation fit."
    assert parse_calls[0]["temperature"] == 0.6
    assert parse_calls[0]["max_output_tokens"] == 9000
    assert parse_calls[0]["timeout"] == 90
    assert parse_calls[0]["truncation"] == "disabled"
    assert package.workflow_trace is not None
    assert package.workflow_trace.workflow_name == "application_package"


def test_manifest_without_requirements_uses_core_artifacts() -> None:
    manifest = build_application_artifact_manifest(make_job(), None)

    assert [item.type for item in manifest] == [
        "application_summary",
        "positioning_strategy",
        "cv_tailoring_notes",
        "missing_information_checklist",
    ]


def test_manifest_uses_requirements_for_variable_artifacts() -> None:
    job = make_job()
    manifest = build_application_artifact_manifest(job, make_requirements(job))

    artifact_types = [item.type for item in manifest]
    labels = [item.label for item in manifest]

    assert "cover_letter" in artifact_types
    assert "document_upload_checklist" in artifact_types
    assert artifact_types.count("form_answer") == 2
    assert "Recommendation code" not in labels
    assert "Portfolio URL" in labels


def test_missing_information_marks_sensitive_user_decisions() -> None:
    job = make_job()
    missing = build_missing_information_defaults(
        get_sample_candidate_profile(),
        make_requirements(job),
    )

    assert any("severe disability" in item for item in missing)
    assert any("Recommendation code" in item for item in missing)
    assert any("Privacy consent" in item for item in missing)


def test_generate_application_package_accepts_fake_generator() -> None:
    job = make_job()

    def fake_generator(candidate_profile, experience_units, received_job, requirements):
        assert candidate_profile == get_sample_candidate_profile()
        assert experience_units == get_sample_experience_units()
        assert received_job == job
        assert requirements is None
        return ApplicationPackage(
            job_id="wrong-job",
            artifacts=[
                ApplicationArtifact(
                    id="summary",
                    type="application_summary",
                    label="Application Summary",
                    required=True,
                    content="Strong automation fit.",
                )
            ],
            missing_information=["Application requirements have not been discovered."],
            selected_experience_units=["exp-001"],
        )

    package = generate_application_package(
        get_sample_candidate_profile(),
        get_sample_experience_units(),
        job,
        None,
        generator=fake_generator,
    )

    assert package.job_id == job.id
    assert package.artifacts[0].id == "summary"
    assert package.selected_experience_units == ["exp-001"]


def test_markdown_render_and_save_round_trip(tmp_path: Path) -> None:
    job = make_job()
    package = ApplicationPackage(
        job_id=job.id,
        artifacts=[
            ApplicationArtifact(
                id="cover-letter",
                type="cover_letter",
                label="Cover Letter",
                required=True,
                content="Dear hiring team, I am interested.",
            )
        ],
        missing_information=["Confirm location."],
    )

    markdown = render_application_package_markdown(package, job)
    json_path, markdown_path = save_application_package(tmp_path, package, job)
    reloaded = load_application_package(tmp_path, job.id)

    assert "# Application Package: Example Co / Automation Engineer" in markdown
    assert "Dear hiring team" in markdown
    assert reloaded == package
    assert json_path.exists()
    assert markdown_path.name == APPLICATION_PACKAGE_MARKDOWN_FILENAME
    assert markdown_path.read_text(encoding="utf-8") == markdown


def test_update_tracker_for_application_package(tmp_path: Path) -> None:
    job = make_job()
    tracker_path = tmp_path / "data" / "runtime" / "jobs.json"
    save_model(
        tracker_path,
        [
            TrackerRecord(
                job_id=job.id,
                title=job.title,
                company=job.company,
                source_url=job.source_url,
                retrieval_mode=job.retrieval_mode,
                status="new",
            )
        ],
    )

    update_tracker_for_application_package(
        tmp_path,
        job.id,
        tmp_path / "data" / "runtime" / "jobs" / job.id / "application_package.json",
    )
    tracker_records = load_model(tracker_path, list[TrackerRecord])

    assert tracker_records[0].status == "application_draft"
    assert tracker_records[0].generated_package_path.endswith("application_package.json")
