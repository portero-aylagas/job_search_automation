from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm_job_extraction import (
    ApplyUrlResolution,
    DynamicJobDetail,
    ExtractedJobData,
    LLMApplyUrlResolutionResponse,
    LLMExtractedJobDataResponse,
    extract_job_data_from_url,
    resolve_apply_url_from_url,
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


def test_llm_job_extraction_schema_constrains_confidence_values() -> None:
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(LLMExtractedJobDataResponse)
    confidence_schema = find_property_schema(schema, "confidence")

    assert confidence_schema is not None
    assert {"type": "string", "enum": ["high", "medium", "low"]} in confidence_schema["anyOf"]


def test_apply_url_resolution_llm_schema_excludes_local_trace_metadata() -> None:
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(LLMApplyUrlResolutionResponse)

    assert "workflow_trace" not in schema["properties"]


def test_extract_job_data_uses_llm_safe_response_model(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []
    parsed_payload = LLMExtractedJobDataResponse(
        title=" Automation Engineer ",
        company="Example Co",
        requirements=["Python", " ", "python"],
        confidence="high",
        dynamic_fields=[
            DynamicJobDetail(
                name="Travel",
                value="10%",
                confidence="medium",
            )
        ],
        missing_or_uncertain=["Salary not listed", ""],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    extracted = extract_job_data_from_url("https://example.com/jobs/automation-engineer")

    assert parse_calls[0]["text_format"] is LLMExtractedJobDataResponse
    assert parse_calls[0]["text_format"] is not ExtractedJobData
    assert parse_calls[0]["temperature"] == 0.0
    assert parse_calls[0]["max_output_tokens"] == 5000
    assert parse_calls[0]["timeout"] == 90
    assert parse_calls[0]["truncation"] == "disabled"
    assert parse_calls[0]["max_tool_calls"] == 4
    assert extracted.title == "Automation Engineer"
    assert extracted.company == "Example Co"
    assert extracted.requirements == ["Python"]
    assert extracted.confidence == "high"
    assert extracted.dynamic_fields == [
        DynamicJobDetail(
            name="Travel",
            value="10%",
            confidence="medium",
        )
    ]
    assert extracted.missing_or_uncertain == ["Salary not listed"]
    assert extracted.workflow_trace is not None
    assert extracted.workflow_trace.workflow_name == "job_extraction"
    assert extracted.workflow_trace.profile_name == "job_extraction"


def test_extract_job_data_normalizes_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed_payload = LLMExtractedJobDataResponse()

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    extracted = extract_job_data_from_url("https://example.com/jobs/automation-engineer")

    assert extracted.confidence == "low"
    assert extracted.workflow_trace is not None
    assert extracted.workflow_trace.operation == "AI job extraction"


def test_resolve_apply_url_uses_resolution_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []
    parsed_payload = LLMApplyUrlResolutionResponse(
        status="resolved",
        apply_url="https://ats.example.com/apply/automation-engineer",
        evidence=["Apply button points to the ATS page."],
        confidence="high",
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    resolution = resolve_apply_url_from_url(
        "https://example.com/jobs/automation-engineer",
        title="Automation Engineer",
        company="Example Co",
    )

    assert parse_calls[0]["text_format"] is LLMApplyUrlResolutionResponse
    assert parse_calls[0]["text_format"] is not ApplyUrlResolution
    assert resolution.status == "resolved"
    assert resolution.apply_url == "https://ats.example.com/apply/automation-engineer"
    assert resolution.evidence == ["Apply button points to the ATS page."]
    assert resolution.confidence == "high"
    assert resolution.workflow_trace is not None
    assert resolution.workflow_trace.workflow_name == "apply_url_resolution"
    assert resolution.workflow_trace.profile_name == "apply_url_resolution"
    assert parse_calls[0]["temperature"] == 0.0
    assert parse_calls[0]["max_output_tokens"] == 3000
    assert parse_calls[0]["timeout"] == 90
    assert parse_calls[0]["truncation"] == "disabled"
    assert parse_calls[0]["max_tool_calls"] == 5
