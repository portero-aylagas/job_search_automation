"""OpenAI provider boundary for structured responses and file uploads."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from src.schemas import AIWorkflowTrace

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class LLMCallProfile(BaseModel):
    """Configuration for one live LLM workflow call."""

    name: str = ""
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    max_retries: int = 2
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0)
    max_tool_calls: int | None = None
    truncation: str = "disabled"


# Most workflows here extract or validate evidence, so we keep them deterministic.
CV_EXTRACTION_PROFILE = LLMCallProfile(
    name="cv_extraction",
    temperature=0.0,
    max_output_tokens=4000,
    timeout_seconds=60,
)
OPTIONAL_DOCUMENT_EXTRACTION_PROFILE = LLMCallProfile(
    name="optional_document_extraction",
    temperature=0.0,
    max_output_tokens=3000,
    timeout_seconds=60,
)
JOB_EXTRACTION_PROFILE = LLMCallProfile(
    name="job_extraction",
    temperature=0.0,
    max_output_tokens=5000,
    timeout_seconds=90,
    max_tool_calls=4,
)
APPLY_URL_RESOLUTION_PROFILE = LLMCallProfile(
    name="apply_url_resolution",
    temperature=0.0,
    max_output_tokens=3000,
    timeout_seconds=90,
    max_tool_calls=5,
)
APPLY_URL_RANKING_PROFILE = LLMCallProfile(
    name="apply_url_ranking",
    temperature=0.0,
    max_output_tokens=2500,
    timeout_seconds=45,
)
APPLICATION_REQUIREMENTS_PROFILE = LLMCallProfile(
    name="application_requirements",
    temperature=0.0,
    max_output_tokens=6000,
    timeout_seconds=60,
)
# Package generation is the only path that writes human-facing draft text.
APPLICATION_PACKAGE_PROFILE = LLMCallProfile(
    name="application_package",
    temperature=0.6,
    max_output_tokens=9000,
    timeout_seconds=90,
)
APPLICATION_FIELD_MAPPING_PROFILE = LLMCallProfile(
    name="application_field_mapping",
    temperature=0.0,
    max_output_tokens=5000,
    timeout_seconds=60,
)
FILE_UPLOAD_TIMEOUT_SECONDS = 60
FILE_UPLOAD_MAX_RETRIES = 1
FILE_UPLOAD_BACKOFF_SECONDS = (1.0,)


@dataclass(slots=True)
class RetryOutcome:
    """Result value paired with the number of provider attempts used."""

    value: Any
    attempt_count: int


def get_openai_client() -> Any:
    """Return a configured OpenAI client for live AI calls."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before using AI-assisted workflows.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    # We keep SDK retries off so retry behavior stays visible in this module.
    return OpenAI(max_retries=0)


def parse_structured_response(
    *,
    input: list[dict[str, Any]],
    text_format: type[StructuredModel],
    operation: str,
    profile: LLMCallProfile,
    trace_sink: Callable[[AIWorkflowTrace], None] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
) -> StructuredModel:
    """Call OpenAI structured outputs and return the parsed project model."""
    client = get_openai_client()
    request: dict[str, Any] = {
        "model": MODEL,
        "input": input,
        "text_format": text_format,
        "temperature": profile.temperature,
        "max_output_tokens": profile.max_output_tokens,
        "timeout": profile.timeout_seconds,
        "truncation": profile.truncation,
    }
    if tools is not None:
        request["tools"] = tools
    if tool_choice is not None:
        request["tool_choice"] = tool_choice
    if profile.max_tool_calls is not None:
        # Tool-enabled workflows use an explicit cap so web search cannot wander indefinitely.
        request["max_tool_calls"] = profile.max_tool_calls

    started_at = time.monotonic()
    outcome = _call_with_retries(
        lambda: client.responses.parse(**request),
        operation=operation,
        max_retries=profile.max_retries,
        backoff_seconds=profile.retry_backoff_seconds,
    )
    duration_ms = int((time.monotonic() - started_at) * 1000)
    response = outcome.value

    if response.output_parsed is None:
        raise RuntimeError(f"{operation} did not return structured data.")
    parsed = response.output_parsed
    if trace_sink is not None:
        trace_sink(
            AIWorkflowTrace(
                workflow_name=profile.name.strip() or operation,
                operation=operation,
                model=MODEL,
                profile_name=profile.name.strip() or "custom",
                temperature=profile.temperature,
                max_output_tokens=profile.max_output_tokens,
                timeout_seconds=profile.timeout_seconds,
                max_retries=profile.max_retries,
                retry_backoff_seconds=list(profile.retry_backoff_seconds),
                max_tool_calls=profile.max_tool_calls,
                truncation=profile.truncation,
                attempt_count=outcome.attempt_count,
                duration_ms=duration_ms,
            )
        )
    return parsed


def upload_user_file(file: Any) -> Any:
    """Upload a user file through the OpenAI API for downstream extraction."""
    client = get_openai_client()

    def create_file() -> Any:
        if hasattr(file, "seek"):
            file.seek(0)
        return client.files.create(
            file=file,
            purpose="user_data",
            timeout=FILE_UPLOAD_TIMEOUT_SECONDS,
        )

    return _call_with_retries(
        create_file,
        operation="AI file upload",
        max_retries=FILE_UPLOAD_MAX_RETRIES,
        backoff_seconds=FILE_UPLOAD_BACKOFF_SECONDS,
    ).value


def _call_with_retries(
    call: Any,
    *,
    operation: str,
    max_retries: int,
    backoff_seconds: tuple[float, ...],
) -> RetryOutcome:
    attempts = max_retries + 1
    for attempt_index in range(attempts):
        try:
            return RetryOutcome(value=call(), attempt_count=attempt_index + 1)
        except Exception as exc:
            if attempt_index >= max_retries or not _is_retryable_error(exc):
                raise RuntimeError(f"{operation} failed: {exc}") from exc
            # Short bounded backoff is enough for transient provider issues without stalling the UI.
            time.sleep(_retry_delay(attempt_index, backoff_seconds))

    raise RuntimeError(f"{operation} failed after retry policy was exhausted.")


def _retry_delay(attempt_index: int, backoff_seconds: tuple[float, ...]) -> float:
    if not backoff_seconds:
        base_delay = 1.0
    else:
        base_delay = backoff_seconds[min(attempt_index, len(backoff_seconds) - 1)]
    return base_delay + random.uniform(0.0, 0.25)


def _is_retryable_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            # Temporary provider overload and rate limits are worth retrying; bad requests are not.
            if status_code in {408, 409, 429} or status_code >= 500:
                return True
            if 400 <= status_code < 500:
                return False

        error_name = current.__class__.__name__.lower()
        if "ratelimit" in error_name or "timeout" in error_name or "connection" in error_name:
            return True
        if isinstance(current, TimeoutError | ConnectionError):
            return True

        current = current.__cause__ or current.__context__
    return False
