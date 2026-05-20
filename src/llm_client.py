from __future__ import annotations

import os
from typing import Any, TypeVar

from pydantic import BaseModel

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def get_openai_client() -> Any:
    """Return a configured OpenAI client for live AI calls."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before extracting job data with AI.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    return OpenAI()


def parse_structured_response(
    *,
    input: list[dict[str, Any]],
    text_format: type[StructuredModel],
    operation: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
) -> StructuredModel:
    """Call OpenAI structured outputs and return the parsed project model."""
    client = get_openai_client()
    request: dict[str, Any] = {
        "model": MODEL,
        "input": input,
        "text_format": text_format,
    }
    if tools is not None:
        request["tools"] = tools
    if tool_choice is not None:
        request["tool_choice"] = tool_choice

    try:
        response = client.responses.parse(**request)
    except Exception as exc:
        raise RuntimeError(f"{operation} failed: {exc}") from exc

    if response.output_parsed is None:
        raise RuntimeError(f"{operation} did not return structured data.")
    return response.output_parsed


def upload_user_file(file: Any) -> Any:
    """Upload a user file through the OpenAI API for downstream extraction."""
    client = get_openai_client()
    try:
        return client.files.create(file=file, purpose="user_data")
    except Exception as exc:
        raise RuntimeError(f"AI file upload failed: {exc}") from exc
