from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.cv_extraction as cv_extraction
from src.cv_extraction import (
    CVDocumentSnapshot,
    LLMCandidateCVExtractedResponse,
    LLMCandidateCVIdentityResponse,
    LLMCandidateSupplementalExtractedResponse,
    extract_cv_data_with_llm,
    extract_optional_document_data_with_llm,
    run_cv_extraction_task,
    run_optional_document_extraction_task,
    save_uploaded_cv,
    save_uploaded_optional_document,
)
from src.schemas import CandidateCVExtracted, CandidateCVIdentity, CandidateSupplementalExtracted


def test_run_cv_extraction_task_uses_agent_nodes(tmp_path: Path) -> None:
    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("CV content that should be handled by the agent.", encoding="utf-8")
    calls = []
    snapshot = CVDocumentSnapshot(
        file_path=str(cv_path),
        file_name="cv.txt",
        file_id="file-cv",
        mime_type="text/plain",
    )
    extracted = CandidateCVExtracted(
        identity=CandidateCVIdentity(full_name="Taylor Rivera", email="taylor@example.com"),
        skills=["Python"],
    )

    def fake_inspector(path: Path) -> CVDocumentSnapshot:
        calls.append("inspect_cv_document_agent")
        assert path == cv_path
        return snapshot

    def fake_extractor(received_snapshot: CVDocumentSnapshot) -> CandidateCVExtracted:
        calls.append("extract_cv_data")
        assert received_snapshot is snapshot
        return extracted

    result = run_cv_extraction_task(
        cv_path,
        inspector=fake_inspector,
        extractor=fake_extractor,
    )

    assert calls == ["inspect_cv_document_agent", "extract_cv_data"]
    assert result == extracted


def test_save_uploaded_cv_rejects_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CV upload is empty"):
        save_uploaded_cv(tmp_path, "cv.pdf", b"")


def test_save_uploaded_cv_rejects_unsupported_file_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CV must use one of these file types"):
        save_uploaded_cv(tmp_path, "cv.exe", b"not a cv")


def test_save_uploaded_optional_document_rejects_oversized_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cv_extraction, "MAX_UPLOAD_BYTES", 3)

    with pytest.raises(ValueError, match="Optional document upload must be"):
        save_uploaded_optional_document(tmp_path, "certificate.pdf", b"1234")


def test_save_uploaded_cv_accepts_supported_file_type(tmp_path: Path) -> None:
    saved_path = save_uploaded_cv(tmp_path, "Taylor CV.PDF", b"%PDF test")

    assert saved_path.name.endswith("-Taylor-CV.PDF")
    assert saved_path.read_bytes() == b"%PDF test"


def test_save_uploaded_cv_does_not_replace_same_second_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FixedDatetime:
        @classmethod
        def now(cls, tz: timezone) -> datetime:
            return datetime(2026, 5, 28, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(cv_extraction, "datetime", FixedDatetime)

    first_path = save_uploaded_cv(tmp_path, "Taylor CV.pdf", b"first")
    second_path = save_uploaded_cv(tmp_path, "Taylor CV.pdf", b"second")

    assert first_path != second_path
    assert first_path.read_bytes() == b"first"
    assert second_path.read_bytes() == b"second"
    assert second_path.name.endswith("-Taylor-CV-2.pdf")


def test_extract_cv_data_with_llm_uploads_file_reference_to_structured_response(
    monkeypatch,
) -> None:
    parse_calls = []
    parsed_payload = LLMCandidateCVExtractedResponse(
        identity=LLMCandidateCVIdentityResponse(
            full_name="Taylor Rivera",
            email="taylor@example.com",
        ),
        work_experience=["Automation Engineer at Example Co", "  "],
        education=["BSc Computer Science"],
        skills=["Python", "SQL", "python"],
        languages=["English"],
        certifications=["Cloud Fundamentals"],
        projects=["Application workflow automation"],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )
    snapshot = CVDocumentSnapshot(
        file_path="/tmp/cv.pdf",
        file_name="cv.pdf",
        file_id="file-cv",
        mime_type="application/pdf",
    )

    extracted = extract_cv_data_with_llm(snapshot)

    assert extracted.identity == CandidateCVIdentity(
        full_name="Taylor Rivera",
        first_name="Taylor",
        last_name="Rivera",
        email="taylor@example.com",
    )
    assert extracted.work_experience == ["Automation Engineer at Example Co"]
    assert extracted.education == ["BSc Computer Science"]
    assert extracted.skills == ["Python", "SQL"]
    assert extracted.languages == ["English"]
    assert extracted.certifications == ["Cloud Fundamentals"]
    assert extracted.projects == ["Application workflow automation"]
    assert extracted.workflow_trace is not None
    assert extracted.workflow_trace.workflow_name == "cv_extraction"
    assert extracted.workflow_trace.prompt_template_name == "cv_extraction.extract_cv_data"
    assert extracted.workflow_trace.prompt_template_hash
    assert extracted.workflow_trace.profile_name == "cv_extraction"
    assert "prompt_template_name" not in parse_calls[0]
    assert "prompt_template_hash" not in parse_calls[0]
    assert parse_calls[0]["text_format"] is LLMCandidateCVExtractedResponse
    assert parse_calls[0]["text_format"] is not CandidateCVExtracted
    assert parse_calls[0]["temperature"] == 0.0
    assert parse_calls[0]["max_output_tokens"] == 4000
    assert parse_calls[0]["timeout"] == 60
    assert parse_calls[0]["truncation"] == "disabled"
    user_content = parse_calls[0]["input"][1]["content"]
    input_file = next(item for item in user_content if item["type"] == "input_file")
    assert input_file == {"type": "input_file", "file_id": "file-cv"}
    assert "filename" not in input_file


def test_run_optional_document_extraction_task_uses_injected_agents(tmp_path: Path) -> None:
    document_path = tmp_path / "certificate.txt"
    document_path.write_text("Cloud Fundamentals certificate", encoding="utf-8")
    calls = []
    snapshot = CVDocumentSnapshot(
        file_path=str(document_path),
        file_name="certificate.txt",
        file_id="file-certificate",
        mime_type="text/plain",
    )
    extracted = CandidateSupplementalExtracted(certifications=["Cloud Fundamentals"])

    def fake_inspector(path: Path) -> CVDocumentSnapshot:
        calls.append("inspect_cv_document_agent")
        assert path == document_path
        return snapshot

    def fake_extractor(received_snapshot: CVDocumentSnapshot) -> CandidateSupplementalExtracted:
        calls.append("extract_optional_document_data")
        assert received_snapshot is snapshot
        return extracted

    result = run_optional_document_extraction_task(
        document_path,
        inspector=fake_inspector,
        extractor=fake_extractor,
    )

    assert calls == ["inspect_cv_document_agent", "extract_optional_document_data"]
    assert result == extracted


def test_extract_optional_document_data_with_llm_uses_structured_response(monkeypatch) -> None:
    parse_calls = []
    parsed_payload = LLMCandidateSupplementalExtractedResponse(
        certifications=["Cloud Fundamentals"],
        references=["Reference letter from Example Manager", ""],
        notes=[" Available on request "],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )
    snapshot = CVDocumentSnapshot(
        file_path="/tmp/reference.pdf",
        file_name="reference.pdf",
        file_id="file-reference",
        mime_type="application/pdf",
    )

    extracted = extract_optional_document_data_with_llm(snapshot)

    assert extracted.certifications == ["Cloud Fundamentals"]
    assert extracted.references == ["Reference letter from Example Manager"]
    assert extracted.notes == ["Available on request"]
    assert extracted.workflow_trace is not None
    assert extracted.workflow_trace.workflow_name == "optional_document_extraction"
    assert extracted.workflow_trace.profile_name == "optional_document_extraction"
    assert parse_calls[0]["text_format"] is LLMCandidateSupplementalExtractedResponse
    assert parse_calls[0]["text_format"] is not CandidateSupplementalExtracted
    assert parse_calls[0]["temperature"] == 0.0
    assert parse_calls[0]["max_output_tokens"] == 3000
    assert parse_calls[0]["timeout"] == 60
    assert parse_calls[0]["truncation"] == "disabled"
    user_content = parse_calls[0]["input"][1]["content"]
    input_file = next(item for item in user_content if item["type"] == "input_file")
    assert input_file == {"type": "input_file", "file_id": "file-reference"}


def test_extract_cv_data_with_llm_normalizes_missing_fields(monkeypatch) -> None:
    parsed_payload = LLMCandidateCVExtractedResponse()

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    extracted = extract_cv_data_with_llm(
        CVDocumentSnapshot(
            file_path="/tmp/cv.pdf",
            file_name="cv.pdf",
            file_id="file-cv",
            mime_type="application/pdf",
        )
    )

    assert extracted.identity == CandidateCVIdentity()
    assert extracted.workflow_trace is not None
    assert extracted.workflow_trace.operation == "AI CV extraction"


def test_normalize_cv_extracted_cleans_review_list_items() -> None:
    response = LLMCandidateCVExtractedResponse(
        work_experience=[
            "Engineering Specialist - Sample Organization, Sample City (2020-2024)\n"
            "- Built internal workflow systems.",
            "Engineering Specialist - Sample Organization, Sample City "
            "(2020-2024)\nBuilt internal workflow systems.",
        ],
        education=[
            "Sample Institute, Sample City - M.Sc. Engineering, 2020-2022\n"
            "Master thesis: Improving quality checks in multi-stage production workflows"
        ],
        skills=["* Python", "Python", "1. SQL"],
    )

    extracted = cv_extraction.normalize_cv_extracted(response)

    assert extracted.work_experience == [
        "Engineering Specialist - Sample Organization, Sample City (2020-2024)\n"
        "Built internal workflow systems."
    ]
    assert extracted.education == [
        "Sample Institute, Sample City - M.Sc. Engineering, 2020-2022",
        "Master thesis: Improving quality checks in multi-stage production workflows",
    ]
    assert extracted.skills == ["Python", "SQL"]


def test_normalize_cv_extracted_uses_gender_or_legacy_salutation() -> None:
    response = LLMCandidateCVExtractedResponse(
        identity=LLMCandidateCVIdentityResponse(salutation="Herr"),
    )

    extracted = cv_extraction.normalize_cv_extracted(response)

    assert extracted.identity.gender == "Male"


def test_normalize_cv_extracted_accepts_diverse_gender() -> None:
    response = LLMCandidateCVExtractedResponse(
        identity=LLMCandidateCVIdentityResponse(gender="Divers"),
    )

    extracted = cv_extraction.normalize_cv_extracted(response)

    assert extracted.identity.gender == "Diverse"


def test_inspect_cv_document_agent_uploads_cv_file(monkeypatch, tmp_path: Path) -> None:
    create_calls = []
    cv_path = tmp_path / "Taylor CV.pdf"
    cv_path.write_bytes(b"%PDF test")

    class FakeFiles:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            assert kwargs["file"].read() == b"%PDF test"
            return SimpleNamespace(id="file-uploaded-cv")

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(files=FakeFiles()),
    )

    snapshot = cv_extraction.inspect_cv_document_agent(cv_path)

    assert create_calls[0]["purpose"] == "user_data"
    assert create_calls[0]["timeout"] == 60
    assert snapshot.file_id == "file-uploaded-cv"
    assert snapshot.file_name == "Taylor CV.pdf"
    assert snapshot.mime_type == "application/pdf"


def test_cv_extraction_module_has_no_rule_parser() -> None:
    assert not hasattr(cv_extraction, "extract_cv_with_rules")
    assert not hasattr(cv_extraction, "read_cv_text")
