from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field


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


def extract_job_data_from_url(source_url: str) -> ExtractedJobData:
    normalized_url = source_url.strip()
    if not normalized_url:
        raise ValueError("Enter a job URL.")
    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Enter a full job URL, including https://.")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before extracting job data with AI.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    client = OpenAI()
    response = client.responses.parse(
        model=os.getenv("OPENAI_JOB_EXTRACTION_MODEL", "gpt-4o-mini"),
        tools=[{"type": "web_search_preview"}],
        input=[
            {
                "role": "system",
                "content": (
                    "You extract job-offer information from public job URLs for a "
                    "human-in-the-loop job application workflow. Use the web search "
                    "tool to inspect the URL. Extract only facts supported by the "
                    "job page. Leave unknown fields empty and list uncertainty in "
                    "missing_or_uncertain. Put application-relevant facts that do "
                    "not fit the fixed schema into dynamic_fields. For each dynamic "
                    "field, create a concise human-readable name, a value, an "
                    "optional category, a short source_text excerpt when available, "
                    "and a confidence level. Dynamic fields are expected and useful; "
                    "do not put them in missing_or_uncertain unless the fact itself "
                    "is unclear. The apply_url field is mandatory for the workflow "
                    "when the page exposes an application action. It must be an "
                    "http or https URL for the action a user would click to apply, "
                    "such as links or buttons labeled Apply, Apply now, Bewerben, "
                    "Jetzt bewerben, Online bewerben, Zur Bewerbung, Karriereportal, "
                    "or Application form. Never put mailto:, email addresses, phone "
                    "numbers, or contact people in apply_url; place those in "
                    "dynamic_fields instead. If the only application path is email "
                    "or the apply action cannot be verified, leave apply_url empty "
                    "and add a clear missing_or_uncertain item. Do not invent salary, "
                    "location, apply requirements, or company data."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract clear application-preparation data from this job URL:\n"
                    f"{normalized_url}\n\n"
                    "Focus on the job offer only. Application form requirements "
                    "such as CV upload, motivation letter, and screening questions "
                    "will be discovered in a later workflow step."
                ),
            },
        ],
        text_format=ExtractedJobData,
    )
    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured job data.")
    return response.output_parsed
