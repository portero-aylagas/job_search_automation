from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm_job_extraction import (
    DynamicJobDetail,
    ExtractedJobData,
    LLMExtractedJobDataResponse,
    extract_job_data_from_url,
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
    assert extracted == ExtractedJobData(
        title="Automation Engineer",
        company="Example Co",
        requirements=["Python"],
        confidence="high",
        dynamic_fields=[
            DynamicJobDetail(
                name="Travel",
                value="10%",
                confidence="medium",
            )
        ],
        missing_or_uncertain=["Salary not listed"],
    )


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

    assert extracted == ExtractedJobData(confidence="low")
