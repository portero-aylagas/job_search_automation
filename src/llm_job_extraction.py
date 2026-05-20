from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src import llm_client
from src.prompt_templates import get_prompt
from src.url_validation import validate_source_url


class DynamicJobDetail(BaseModel):
    name: str
    value: str
    category: str = ""
    source_text: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class ExtractedJobData(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    remote_policy: str = ""
    apply_url: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    salary: str = ""
    posted_date: str = ""
    source_job_id: str = ""
    confidence: str = ""
    dynamic_fields: list[DynamicJobDetail] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)


class RejectedApplyCandidate(BaseModel):
    url: str = ""
    reason: str = ""
    evidence: str = ""


class ApplyUrlResolution(BaseModel):
    status: Literal["resolved", "needs_review", "not_found"] = "not_found"
    apply_url: str = ""
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)
    rejected_candidates: list[RejectedApplyCandidate] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


def _web_search_tool() -> dict:
    return {
        "type": "web_search",
        "search_context_size": "high",
    }


def extract_job_data_from_url(source_url: str) -> ExtractedJobData:
    normalized_url = validate_source_url(source_url)

    return llm_client.parse_structured_response(
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": get_prompt("llm_job_extraction", "extract_job_data", "system"),
            },
            {
                "role": "user",
                "content": get_prompt(
                    "llm_job_extraction",
                    "extract_job_data",
                    "user",
                    normalized_url=normalized_url,
                ),
            },
        ],
        text_format=ExtractedJobData,
        operation="AI job extraction",
    )


def resolve_apply_url_from_url(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
) -> ApplyUrlResolution:
    normalized_url = validate_source_url(source_url)

    return llm_client.parse_structured_response(
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": get_prompt("llm_job_extraction", "resolve_apply_url", "system"),
            },
            {
                "role": "user",
                "content": get_prompt(
                    "llm_job_extraction",
                    "resolve_apply_url",
                    "user",
                    normalized_url=normalized_url,
                    title=title.strip() or "Unknown",
                    company=company.strip() or "Unknown",
                ),
            },
        ],
        text_format=ApplyUrlResolution,
        operation="AI apply URL resolution",
    )
