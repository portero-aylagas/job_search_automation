from __future__ import annotations

from pathlib import Path

from src import app_workflow
from src.llm_job_extraction import ApplyUrlResolution, ExtractedJobData
from src.schemas import CandidateProfile


def test_app_workflow_has_no_legacy_ui_dependency() -> None:
    source = Path("src/app_workflow.py").read_text(encoding="utf-8")

    assert "stream" + "lit" not in source


def test_load_app_data_uses_supplied_base_dir(tmp_path: Path) -> None:
    profile, tracker_records = app_workflow.load_app_data(tmp_path)

    assert profile.candidate_profile.profile_status == "draft"
    assert tracker_records == []
    assert (tmp_path / "data" / "candidate_profile.json").is_file()
    assert (tmp_path / "data" / "runtime" / "jobs.json").is_file()


def test_candidate_profile_save_and_load_dedupe_reuploaded_optional_documents(
    tmp_path: Path,
) -> None:
    profile = CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "optional_documents": [
                        {
                            "file_path": "/tmp/20240101120000-language-certificate.pdf",
                            "file_name": "language-certificate.pdf",
                            "document_type": "certificate",
                            "parsed": True,
                        },
                        {
                            "file_path": "/tmp/20240101120500-safety-certificate.pdf",
                            "file_name": "safety-certificate.pdf",
                            "document_type": "certificate",
                            "parsed": True,
                        },
                        {
                            "file_path": "/tmp/20240101121000-language-certificate.pdf",
                            "file_name": "language-certificate.pdf",
                            "document_type": "certificate",
                            "parsed": True,
                        },
                        {
                            "file_path": "/tmp/20240101121500-manager-reference.pdf",
                            "document_type": "reference",
                            "parsed": True,
                        },
                        {
                            "file_path": "/tmp/20240101122000-manager-reference.pdf",
                            "document_type": "reference",
                            "parsed": True,
                        },
                    ]
                },
            }
        }
    )

    app_workflow.save_candidate_profile(tmp_path, profile)

    loaded = app_workflow.load_candidate_profile(tmp_path)
    documents = loaded.candidate_profile.source_documents.optional_documents
    assert [(document.document_type, document.file_path) for document in documents] == [
        ("certificate", "/tmp/20240101121000-language-certificate.pdf"),
        ("certificate", "/tmp/20240101120500-safety-certificate.pdf"),
        ("reference", "/tmp/20240101122000-manager-reference.pdf"),
    ]


def test_extract_job_intake_data_accepts_fake_extractor_and_resolver() -> None:
    calls = []

    def fake_extractor(source_url: str) -> ExtractedJobData:
        calls.append(("extract", source_url))
        return ExtractedJobData(
            title="Automation Engineer",
            company="Example Co",
            source_job_id="external-123",
        )

    def fake_resolver(
        source_url: str,
        *,
        title: str,
        company: str,
        source_job_id: str,
    ) -> ApplyUrlResolution:
        calls.append(("resolve", source_url, title, company, source_job_id))
        return ApplyUrlResolution(
            status="resolved",
            apply_url="https://example.com/apply/automation-engineer",
        )

    result = app_workflow.extract_job_intake_data(
        "https://example.com/jobs/automation-engineer",
        extractor=fake_extractor,
        resolver=fake_resolver,
    )

    assert result.extracted.title == "Automation Engineer"
    assert result.apply_resolution.status == "resolved"
    assert calls == [
        ("extract", "https://example.com/jobs/automation-engineer"),
        (
            "resolve",
            "https://example.com/jobs/automation-engineer",
            "Automation Engineer",
            "Example Co",
            "external-123",
        ),
    ]


def test_apply_resolution_details_marks_manual_unverified_url() -> None:
    details = app_workflow.apply_resolution_details(
        "https://example.com/apply/automation-engineer",
        "https://example.com/jobs/automation-engineer",
        None,
    )

    assert details["status"] == "manual_review"
    assert details["verified_by_resolver"] is False
    assert details["manual_override"] is True


def test_resolved_apply_url_rejects_invalid_resolved_candidate() -> None:
    resolution = ApplyUrlResolution(
        status="resolved",
        apply_url="mailto:jobs@example.com",
    )

    assert app_workflow.resolved_apply_url(
        "https://example.com/jobs/automation-engineer",
        resolution,
    ) == ""
