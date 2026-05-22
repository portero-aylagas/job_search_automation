from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application_package import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME,
    LLMApplicationArtifact,
    LLMApplicationPackageResponse,
    apply_application_package_quality_checks,
    apply_manual_artifact_edits,
    build_application_artifact_manifest,
    build_missing_information_defaults,
    export_cover_letter_artifact,
    generate_application_package,
    generate_application_package_with_llm,
    load_application_package,
    reject_application_package,
    render_application_package_markdown,
    save_application_package,
    update_tracker_for_application_package,
)
from src.job_intake import create_job_listing
from src.paths import application_package_artifacts_dir
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


def test_generate_application_package_reports_llm_error_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = make_job()

    def unavailable_llm(candidate_profile, experience_units, received_job, requirements):
        raise RuntimeError("Set OPENAI_API_KEY before using AI-assisted workflows.")

    monkeypatch.setattr(
        "src.application_package.generate_application_package_with_llm",
        unavailable_llm,
    )

    with pytest.raises(RuntimeError, match="Set OPENAI_API_KEY"):
        generate_application_package(
            get_sample_candidate_profile(),
            get_sample_experience_units(),
            job,
            make_requirements(job),
        )

    assert load_application_package(tmp_path, job.id) is None


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


def test_application_package_adds_artifact_traceability_metadata() -> None:
    job = make_job()

    def fake_generator(candidate_profile, experience_units, received_job, requirements):
        assert requirements is not None
        return ApplicationPackage(
            job_id=received_job.id,
            artifacts=[
                ApplicationArtifact(
                    id="screening-answer",
                    type="form_answer",
                    label="Screening Answer",
                    required=True,
                    source_prompt="Which locations are suitable for you?",
                    source_requirement="Select all suitable locations.",
                    content="Remote and hybrid locations are suitable.",
                )
            ],
            selected_experience_units=["exp-001"],
        )

    package = generate_application_package(
        get_sample_candidate_profile(),
        get_sample_experience_units(),
        job,
        make_requirements(job),
        generator=fake_generator,
    )

    traceability = package.artifacts[0].metadata["traceability"]

    assert traceability["source_requirements"] == [
        {
            "kind": "screening_question",
            "label": "Which locations are suitable for you?",
            "evidence": "Select all suitable locations.",
            "confidence": "high",
        }
    ]
    assert traceability["source_experience_units"][0]["id"] == "exp-001"
    assert traceability["source_experience_units"][0]["title"] == (
        "Workflow Automation Analyst"
    )
    assert "Automated weekly KPI reporting" in (
        traceability["source_experience_units"][0]["evidence_points"][0]
    )


def test_manual_artifact_edits_mark_artifacts_without_mutating_original() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        artifacts=[
            ApplicationArtifact(
                id="cover-letter",
                type="cover_letter",
                label="Cover Letter",
                content="Draft text.",
            ),
            ApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Summary",
                content="Keep this.",
            ),
        ],
    )

    edited = apply_manual_artifact_edits(
        package,
        {"cover-letter": "Reviewed text.", "summary": "Keep this."},
    )

    assert package.artifacts[0].content == "Draft text."
    assert edited.artifacts[0].content == "Reviewed text."
    assert edited.artifacts[0].status == "manually_edited"
    assert edited.artifacts[0].metadata["manual_edit"] is True
    assert edited.artifacts[1].status == "draft"
    assert edited.generation_notes == ["Manual edits saved for: Cover Letter"]


def test_reject_application_package_preserves_artifacts_and_records_reason() -> None:
    package = ApplicationPackage(
        job_id="job-001",
        artifacts=[
            ApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Summary",
                content="Draft text.",
            )
        ],
        generation_notes=["Initial generation."],
    )

    rejected = reject_application_package(package, "Overstates Python experience.")

    assert package.status == "draft"
    assert rejected.status == "rejected"
    assert rejected.artifacts[0].content == "Draft text."
    assert rejected.generation_notes == [
        "Initial generation.",
        "Rejected by reviewer: Overstates Python experience.",
    ]


def test_quality_checks_flag_unsupported_skill_overclaims() -> None:
    job = create_job_listing(
        title="Platform Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/platform-automation-engineer",
        apply_url="https://example.com/apply/platform-automation-engineer",
        requirements=["Kubernetes"],
    )
    package = ApplicationPackage(
        job_id=job.id,
        artifacts=[
            ApplicationArtifact(
                id="cover-letter",
                type="cover_letter",
                label="Cover Letter",
                content="I have experience with Kubernetes in production systems.",
            )
        ],
    )

    checked = apply_application_package_quality_checks(
        package,
        get_sample_candidate_profile(),
        job,
    )

    assert checked.status == "needs_review"
    assert checked.artifacts[0].status == "needs_review"
    assert checked.artifacts[0].metadata["quality_findings"] == [
        "Claims experience with unsupported requirement: Kubernetes"
    ]
    assert any("unsupported requirement" in item for item in checked.missing_information)


def test_quality_checks_flag_sensitive_generated_answers() -> None:
    job = make_job()
    package = ApplicationPackage(
        job_id=job.id,
        artifacts=[
            ApplicationArtifact(
                id="disability-answer",
                type="form_answer",
                label="Severe disability disclosure",
                source_prompt="Do you have a severe disability you want to disclose?",
                content="No.",
            )
        ],
    )

    checked = apply_application_package_quality_checks(
        package,
        get_sample_candidate_profile(),
        job,
    )

    assert checked.status == "needs_review"
    assert checked.artifacts[0].status == "needs_review"
    assert checked.artifacts[0].metadata["quality_findings"] == [
        "Generated answer for a sensitive or user-decision field."
    ]
    assert any("sensitive" in item for item in checked.missing_information)


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
                metadata={
                    "traceability": {
                        "source_requirements": [
                            {
                                "kind": "motivation_letter",
                                "label": "Cover letter",
                                "evidence": "Please upload a cover letter.",
                                "confidence": "high",
                            }
                        ],
                        "source_experience_units": [
                            {
                                "id": "exp-001",
                                "title": "Workflow Automation Analyst",
                                "organization": "Northwind Logistics",
                            }
                        ],
                    }
                },
            )
        ],
        missing_information=["Confirm location."],
    )

    markdown = render_application_package_markdown(package, job)
    json_path, markdown_path = save_application_package(tmp_path, package, job)
    reloaded = load_application_package(tmp_path, job.id)

    assert "# Application Package: Example Co / Automation Engineer" in markdown
    assert "Dear hiring team" in markdown
    assert "## Cover Letter" in markdown
    assert "### Traceability" in markdown
    assert "Cover letter (confidence: high)" in markdown
    assert "Workflow Automation Analyst / Northwind Logistics" in markdown
    assert reloaded == package
    assert json_path.exists()
    assert markdown_path.name == APPLICATION_PACKAGE_MARKDOWN_FILENAME
    assert markdown_path.read_text(encoding="utf-8") == markdown


def test_save_application_package_exports_cover_letter_artifact_file(
    tmp_path: Path,
) -> None:
    job = make_job()
    package = ApplicationPackage(
        job_id=job.id,
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                content="Dear hiring team,\n\nGenerated cover letter.",
            )
        ],
    )

    save_application_package(tmp_path, package, job)
    exported_path = (
        application_package_artifacts_dir(tmp_path, job.id) / "cover-letter-draft.pdf"
    )
    reloaded = load_application_package(tmp_path, job.id)

    assert exported_path.exists()
    assert exported_path.read_bytes().startswith(b"%PDF")
    assert reloaded is not None
    assert reloaded.artifacts[0].metadata["generated_file_path"] == str(exported_path)
    assert reloaded.artifacts[0].metadata["generated_file_format"] == "pdf"
    assert reloaded.artifacts[0].metadata["generated_file_mime_type"] == "application/pdf"


def test_export_cover_letter_artifact_writes_to_selected_folder(tmp_path: Path) -> None:
    package = ApplicationPackage(
        job_id="job-001",
        artifacts=[
            ApplicationArtifact(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                content="Dear hiring team,\n\nReviewed cover letter.",
            )
        ],
    )
    destination = tmp_path / "selected-downloads"

    exported_path = export_cover_letter_artifact(package, destination)

    assert exported_path == destination / "cover-letter-draft.pdf"
    assert exported_path.exists()
    assert exported_path.read_bytes().startswith(b"%PDF")
    assert package.artifacts[0].metadata["downloaded_file_path"] == str(exported_path)
    assert package.artifacts[0].metadata["downloaded_file_format"] == "pdf"


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
