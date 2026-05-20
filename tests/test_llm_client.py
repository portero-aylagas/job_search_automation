from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src import llm_client


class DummyResponse(BaseModel):
    value: str


class RetryableProviderError(Exception):
    status_code = 429


class TemporaryProviderError(Exception):
    status_code = 500


class BadRequestProviderError(Exception):
    status_code = 400


def test_structured_response_request_uses_explicit_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []
    parsed_payload = DummyResponse(value="ok")

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    profile = llm_client.LLMCallProfile(
        temperature=0.2,
        max_output_tokens=1234,
        timeout_seconds=30,
        max_tool_calls=7,
    )
    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    result = llm_client.parse_structured_response(
        input=[{"role": "user", "content": "Test"}],
        text_format=DummyResponse,
        operation="Test operation",
        profile=profile,
        tools=[{"type": "web_search"}],
        tool_choice={"type": "web_search"},
    )

    assert result == parsed_payload
    request = parse_calls[0]
    assert request["temperature"] == 0.2
    assert request["max_output_tokens"] == 1234
    assert request["timeout"] == 30
    assert request["truncation"] == "disabled"
    assert request["max_tool_calls"] == 7


def test_structured_response_emits_trace_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_calls = []
    trace_payload = []
    parsed_payload = DummyResponse(value="ok")

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    profile = llm_client.LLMCallProfile(
        name="traceable_workflow",
        temperature=0.2,
        max_output_tokens=1234,
        timeout_seconds=30,
        max_tool_calls=7,
    )
    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )
    monkeypatch.setattr("src.llm_client.time.monotonic", lambda: 100.0)

    result = llm_client.parse_structured_response(
        input=[{"role": "user", "content": "Test"}],
        text_format=DummyResponse,
        operation="Trace test",
        profile=profile,
        trace_sink=trace_payload.append,
    )

    assert result == parsed_payload
    assert len(trace_payload) == 1
    trace = trace_payload[0]
    assert trace.workflow_name == "traceable_workflow"
    assert trace.operation == "Trace test"
    assert trace.model == llm_client.MODEL
    assert trace.profile_name == "traceable_workflow"
    assert trace.temperature == 0.2
    assert trace.max_output_tokens == 1234
    assert trace.timeout_seconds == 30
    assert trace.max_retries == 2
    assert trace.max_tool_calls == 7
    assert trace.attempt_count == 1
    assert trace.duration_ms == 0
    assert trace.recorded_at
    assert parse_calls[0]["truncation"] == "disabled"


def test_retryable_structured_failures_retry_as_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []
    parsed_payload = DummyResponse(value="ok")
    monkeypatch.setattr("src.llm_client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.llm_client.random.uniform", lambda _start, _end: 0.0)

    class FakeResponses:
        def parse(self, **_kwargs):
            attempts.append("parse")
            if len(attempts) < 3:
                raise RetryableProviderError("rate limited")
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    result = llm_client.parse_structured_response(
        input=[{"role": "user", "content": "Test"}],
        text_format=DummyResponse,
        operation="Retry test",
        profile=llm_client.LLMCallProfile(
            temperature=0.0,
            max_output_tokens=100,
            timeout_seconds=10,
            max_retries=2,
        ),
    )

    assert result == parsed_payload
    assert attempts == ["parse", "parse", "parse"]


def test_non_retryable_structured_failures_do_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    class FakeResponses:
        def parse(self, **_kwargs):
            attempts.append("parse")
            raise BadRequestProviderError("bad request")

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    with pytest.raises(RuntimeError, match="Non-retry test failed: bad request"):
        llm_client.parse_structured_response(
            input=[{"role": "user", "content": "Test"}],
            text_format=DummyResponse,
            operation="Non-retry test",
            profile=llm_client.LLMCallProfile(
                temperature=0.0,
                max_output_tokens=100,
                timeout_seconds=10,
                max_retries=2,
            ),
        )

    assert attempts == ["parse"]


def test_missing_api_key_fails_before_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = []

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            constructed.append("provider")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    with pytest.raises(RuntimeError, match="Set OPENAI_API_KEY"):
        llm_client.get_openai_client()

    assert constructed == []


def test_provider_client_disables_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    llm_client.get_openai_client()

    assert constructed == [{"max_retries": 0}]


def test_file_upload_uses_timeout_and_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    create_calls = []
    monkeypatch.setattr("src.llm_client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.llm_client.random.uniform", lambda _start, _end: 0.0)

    class FakeFiles:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            if len(create_calls) == 1:
                raise TemporaryProviderError("temporary outage")
            return SimpleNamespace(id="file-uploaded")

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(files=FakeFiles()),
    )

    uploaded = llm_client.upload_user_file(io.BytesIO(b"file bytes"))

    assert uploaded.id == "file-uploaded"
    assert len(create_calls) == 2
    assert create_calls[0]["timeout"] == 60
    assert create_calls[1]["timeout"] == 60
