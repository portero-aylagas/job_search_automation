from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

MODEL = "gpt-5.5"


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


def _validate_source_url(source_url: str) -> str:
    normalized_url = source_url.strip()

    if not normalized_url:
        raise ValueError("Enter a job URL.")

    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Enter a full job URL, including https://.")

    return normalized_url


def _get_openai_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before extracting job data with AI.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    return OpenAI()


def _web_search_tool() -> dict:
    return {
        "type": "web_search",
        "search_context_size": "high",
    }


def extract_job_data_from_url(source_url: str) -> ExtractedJobData:
    normalized_url = _validate_source_url(source_url)
    client = _get_openai_client()

    response = client.responses.parse(
        model=MODEL,
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": (
                    "You extract job-offer information from public job URLs for a "
                    "human-in-the-loop job application workflow.\n\n"
                    "Use web search/open-page capability to inspect the supplied URL. "
                    "Focus only on the job offer page and facts supported by that page.\n\n"
                    "Leave unknown fields empty. Do not invent salary, location, company, "
                    "posted date, job ID, requirements, or responsibilities.\n\n"
                    "Put application-relevant facts that do not fit the fixed schema into "
                    "dynamic_fields. For each dynamic field, create a concise name, value, "
                    "optional category, short source_text excerpt when available, and "
                    "confidence level.\n\n"
                    "Do not resolve apply_url here. Leave apply_url empty unless it is "
                    "directly and unambiguously visible in the job page text. A separate "
                    "resolver handles application URLs."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract application-preparation data from this job URL:\n"
                    f"{normalized_url}\n\n"
                    "Focus on the job offer only. Do not resolve the application "
                    "destination here."
                ),
            },
        ],
        text_format=ExtractedJobData,
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured job data.")

    return response.output_parsed


def resolve_apply_url_from_url(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
) -> ApplyUrlResolution:
    normalized_url = _validate_source_url(source_url)
    client = _get_openai_client()

    response = client.responses.parse(
        model=MODEL,
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": (
                    "You resolve the real application destination for a public job offer.\n\n"
                    "Use web search/open-page capability. Do not guess. You must inspect "
                    "the supplied job page and identify the actual URL a candidate reaches "
                    "to begin applying.\n\n"
                    "Important: do not trust the first apply-looking URL blindly. Some "
                    "pages expose intermediate URLs such as talent-community pages, tracking "
                    "links, job-alert pages, or URLs that redirect to generic career pages. "
                    "Those are not valid resolved apply URLs unless they preserve the same "
                    "job identity after opening.\n\n"
                    "Process:\n"
                    "1. Open or inspect the source job page.\n"
                    "2. Find links/buttons with labels such as Apply, Apply now, Bewerben, "
                    "Jetzt bewerben, Online bewerben, Zur Bewerbung, Application form, "
                    "Karriereportal, or equivalent wording.\n"
                    "3. For every plausible candidate, verify whether the candidate URL or "
                    "its opened/redirected destination still refers to the same job.\n"
                    "4. Prefer the final application URL that preserves the job identity.\n"
                    "5. Reject candidates that lose the job identity, redirect to a generic "
                    "career homepage, point to talent community signup, job alerts, saved "
                    "search, newsletter signup, generic login without job context, contact "
                    "page, mailto link, phone number, or the original job-description page.\n\n"
                    "Job identity can be preserved by any of these signals:\n"
                    "- same job title\n"
                    "- same company\n"
                    "- same location\n"
                    "- same requisition ID or job ID\n"
                    "- application URL contains a job/requisition parameter\n"
                    "- destination page clearly shows the same role\n\n"
                    "Return only HTTP or HTTPS URLs. Never return mailto links, email "
                    "addresses, phone numbers, contact-person URLs, or the original "
                    "job-description URL.\n\n"
                    "If two URLs point to the same application but one contains only tracking "
                    "parameters, prefer the cleaner URL when the job identity is still "
                    "preserved. If the tracking URL is the only verified URL, returning it is "
                    "acceptable.\n\n"
                    "If an apply button exists but the final job-preserving URL cannot be "
                    "verified, set status='needs_review' and leave apply_url empty.\n\n"
                    "If no application destination exists or the only action is email, set "
                    "status='not_found' or status='needs_review' and leave apply_url empty.\n\n"
                    "Use rejected_candidates to record plausible URLs that were rejected and "
                    "why. Use evidence for short facts that justify the final decision."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Resolve the real application URL for this job offer.\n\n"
                    f"Source job URL: {normalized_url}\n"
                    f"Known title: {title.strip() or 'Unknown'}\n"
                    f"Known company: {company.strip() or 'Unknown'}\n\n"
                    "Return the final job-preserving application URL. Do not return an "
                    "intermediate URL if it redirects to a generic career page or loses the "
                    "job identity."
                ),
            },
        ],
        text_format=ApplyUrlResolution,
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured apply URL data.")

    return response.output_parsed