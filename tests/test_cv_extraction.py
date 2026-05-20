from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import src.cv_extraction as cv_extraction
from src.cv_extraction import (
    CVDocumentSnapshot,
    extract_cv_data_with_llm,
    extract_optional_document_data_with_llm,
    run_cv_extraction_task,
    run_optional_document_extraction_task,
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


def test_extract_cv_data_with_llm_uploads_file_reference_to_structured_response(
    monkeypatch,
) -> None:
    parse_calls = []
    parsed_payload = CandidateCVExtracted(
        identity=CandidateCVIdentity(full_name="Taylor Rivera", email="taylor@example.com"),
        work_experience=["Automation Engineer at Example Co"],
        education=["BSc Computer Science"],
        skills=["Python", "SQL"],
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

    assert extracted == parsed_payload
    assert parse_calls[0]["text_format"] is CandidateCVExtracted
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
    parsed_payload = CandidateSupplementalExtracted(
        certifications=["Cloud Fundamentals"],
        references=["Reference letter from Example Manager"],
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

    assert extracted == parsed_payload
    assert parse_calls[0]["text_format"] is CandidateSupplementalExtracted
    user_content = parse_calls[0]["input"][1]["content"]
    input_file = next(item for item in user_content if item["type"] == "input_file")
    assert input_file == {"type": "input_file", "file_id": "file-reference"}


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
    assert snapshot.file_id == "file-uploaded-cv"
    assert snapshot.file_name == "Taylor CV.pdf"
    assert snapshot.mime_type == "application/pdf"


def test_cv_extraction_module_has_no_rule_parser() -> None:
    assert not hasattr(cv_extraction, "extract_cv_with_rules")
    assert not hasattr(cv_extraction, "read_cv_text")
