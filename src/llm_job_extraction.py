"""LLM-assisted job extraction models and provider calls."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src import llm_client
from src.prompt_templates import get_prompt
from src.schemas import AIWorkflowTrace, ConfidenceLevel
from src.url_validation import validate_source_url


class DynamicJobDetail(BaseModel):
    """Flexible extracted job detail that does not fit the fixed job schema."""

    name: str
    value: str
    category: str = ""
    source_text: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class ExtractedJobData(BaseModel):
    """Normalized job-offer data returned to the intake workflow."""

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
    confidence: ConfidenceLevel = "low"
    dynamic_fields: list[DynamicJobDetail] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)
    workflow_trace: AIWorkflowTrace | None = None


class LLMExtractedJobDataResponse(BaseModel):
    """LLM-safe job extraction schema before local normalization."""

    title: str | None = None
    company: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    apply_url: str | None = None
    description: str | None = None
    requirements: list[str] | None = None
    responsibilities: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    salary: str | None = None
    posted_date: str | None = None
    source_job_id: str | None = None
    confidence: ConfidenceLevel | None = None
    dynamic_fields: list[DynamicJobDetail] | None = None
    missing_or_uncertain: list[str] | None = None


class RejectedApplyCandidate(BaseModel):
    """Apply URL candidate rejected during resolution or review."""

    url: str = ""
    reason: str = ""
    evidence: str = ""


class ApplyUrlResolution(BaseModel):
    """Resolved apply URL result with evidence and rejected candidates."""

    status: Literal["resolved", "needs_review", "not_found"] = "not_found"
    apply_url: str = ""
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)
    rejected_candidates: list[RejectedApplyCandidate] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    workflow_trace: AIWorkflowTrace | None = None


class LLMApplyUrlResolutionResponse(BaseModel):
    """LLM-safe apply URL resolution schema without local trace metadata."""

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
    """Extract structured job-offer data from a source URL with web search."""

    normalized_url = validate_source_url(source_url)
    workflow_trace: AIWorkflowTrace | None = None

    def capture_trace(trace: AIWorkflowTrace) -> None:
        nonlocal workflow_trace
        workflow_trace = trace

    response = llm_client.parse_structured_response(
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
        text_format=LLMExtractedJobDataResponse,
        operation="AI job extraction",
        # Job extraction should describe what the source says, not invent missing fields.
        profile=llm_client.JOB_EXTRACTION_PROFILE,
        trace_sink=capture_trace,
    )
    extracted = normalize_extracted_job_data(response)
    extracted.workflow_trace = workflow_trace
    return extracted


def resolve_apply_url_from_url(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
) -> ApplyUrlResolution:
    """Resolve the likely application URL for a job source URL with web search."""

    normalized_url = validate_source_url(source_url)
    workflow_trace: AIWorkflowTrace | None = None

    def capture_trace(trace: AIWorkflowTrace) -> None:
        nonlocal workflow_trace
        workflow_trace = trace

    response = llm_client.parse_structured_response(
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
        text_format=LLMApplyUrlResolutionResponse,
        operation="AI apply URL resolution",
        # URL resolution is a verification task, so we keep it deterministic as well.
        profile=llm_client.APPLY_URL_RESOLUTION_PROFILE,
        trace_sink=capture_trace,
    )
    resolution = ApplyUrlResolution.model_validate(response.model_dump(mode="json"))
    resolution.workflow_trace = workflow_trace
    return resolution


def normalize_extracted_job_data(response: LLMExtractedJobDataResponse) -> ExtractedJobData:
    """Convert nullable LLM job extraction output into the local intake model."""

    return ExtractedJobData(
        title=_normalize_text(response.title),
        company=_normalize_text(response.company),
        location=_normalize_text(response.location),
        remote_policy=_normalize_text(response.remote_policy),
        apply_url=_normalize_text(response.apply_url),
        description=_normalize_text(response.description),
        requirements=_normalize_string_list(response.requirements),
        responsibilities=_normalize_string_list(response.responsibilities),
        nice_to_have_skills=_normalize_string_list(response.nice_to_have_skills),
        salary=_normalize_text(response.salary),
        posted_date=_normalize_text(response.posted_date),
        source_job_id=_normalize_text(response.source_job_id),
        confidence=response.confidence or "low",
        dynamic_fields=response.dynamic_fields or [],
        missing_or_uncertain=_normalize_string_list(response.missing_or_uncertain),
    )


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        normalized.append(item)
        seen.add(key)
    return normalized


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()
