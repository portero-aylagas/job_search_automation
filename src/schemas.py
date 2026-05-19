from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

TrackerStatus = Literal[
    "new",
    "analyzed",
    "interesting",
    "rejected_by_user",
    "application_draft",
    "ready_to_apply",
    "applied_manually",
    "applied_with_agent_assistance",
    "interview",
    "rejected",
    "offer",
    "closed",
]


class CandidateProfile(BaseModel):
    id: str
    full_name: str
    professional_summary: str
    target_roles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    salary_expectation: str | None = None
    constraints: list[str] = Field(default_factory=list)
    documents_used: list[str] = Field(default_factory=list)


class ExperienceUnit(BaseModel):
    id: str
    title: str
    organization: str
    date_range: str
    summary: str
    skills: list[str] = Field(default_factory=list)
    evidence_points: list[str] = Field(default_factory=list)


class JobListing(BaseModel):
    id: str
    title: str
    company: str
    source_url: HttpUrl
    retrieval_mode: str
    source_job_id: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    apply_url: HttpUrl | None = None
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    salary: str | None = None
    posted_date: str | None = None
    job_details: dict[str, Any] = Field(default_factory=dict)


ConfidenceLevel = Literal["high", "medium", "low"]


class ApplicationRequirementFinding(BaseModel):
    label: str
    required: bool = False
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"
    constraints: list[str] = Field(default_factory=list)


class ApplicationScreeningQuestion(BaseModel):
    question: str
    required: bool = False
    input_type: str = ""
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"


class ApplicationFormField(BaseModel):
    name: str = ""
    label: str
    required: bool = False
    input_type: str = ""
    options: list[str] = Field(default_factory=list)
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"


class ApplicationPageControl(BaseModel):
    kind: str = ""
    name: str = ""
    label: str = ""
    input_type: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""


class ApplicationPageFormSummary(BaseModel):
    action: str = ""
    method: str = "get"
    labels: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    controls: list[ApplicationPageControl] = Field(default_factory=list)


class ApplicationPageSnapshot(BaseModel):
    requested_url: str
    final_url: str = ""
    fetch_status: int | None = None
    content_type: str = ""
    page_title: str = ""
    evidence_matches: list[str] = Field(default_factory=list)
    forms: list[ApplicationPageFormSummary] = Field(default_factory=list)
    controls: list[ApplicationPageControl] = Field(default_factory=list)
    embedded_json_summaries: list[dict[str, Any]] = Field(default_factory=list)
    job_preserving_signals: list[str] = Field(default_factory=list)
    visible_text_excerpt: str = ""
    raw_html_excerpt: str = ""
    errors: list[str] = Field(default_factory=list)
    browser_fallback_used: bool = False


class ApplicationRequirements(BaseModel):
    job_id: str
    apply_url: HttpUrl
    source_url: HttpUrl
    status: Literal["discovered", "blocked"] = "discovered"
    blocked_reason: str | None = None
    job_preserving: bool = False
    required_documents: list[ApplicationRequirementFinding] = Field(default_factory=list)
    upload_expectations: list[ApplicationRequirementFinding] = Field(default_factory=list)
    screening_questions: list[ApplicationScreeningQuestion] = Field(default_factory=list)
    custom_form_fields: list[ApplicationFormField] = Field(default_factory=list)
    profile_fields: list[ApplicationFormField] = Field(default_factory=list)
    motivation_letter: ApplicationRequirementFinding | None = None
    consent_requirements: list[ApplicationRequirementFinding] = Field(default_factory=list)
    privacy_login_ats_gates: list[ApplicationRequirementFinding] = Field(default_factory=list)
    deadlines: list[ApplicationRequirementFinding] = Field(default_factory=list)
    contact_or_fallback: list[ApplicationRequirementFinding] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "medium"


class TrackerRecord(BaseModel):
    job_id: str
    title: str
    company: str
    source_url: HttpUrl
    location: str | None = None
    retrieval_mode: str
    match_score: float | None = None
    status: TrackerStatus = "new"
    notes: str | None = None
    generated_package_path: str | None = None
