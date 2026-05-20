from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

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

EmploymentType = Literal[
    "full_time",
    "part_time",
    "contract",
    "freelance",
]

RemotePreference = Literal["remote", "hybrid", "onsite"]

_REMOTE_PREFERENCE_ALIASES: dict[str, RemotePreference] = {
    "remote": "remote",
    "fully remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on site": "onsite",
    "on-site": "onsite",
}

_WORK_AUTHORIZATION_ALIASES = {
    "eu authorized": "eu_authorized",
    "eu work authorized": "eu_authorized",
    "eu sponsorship required": "eu_sponsorship_required",
    "eu sponsorship needed": "eu_sponsorship_required",
}

_EMPLOYMENT_TYPE_ALIASES = {
    "full time": "full_time",
    "full-time": "full_time",
    "full_time": "full_time",
    "part time": "part_time",
    "part-time": "part_time",
    "part_time": "part_time",
    "contract": "contract",
    "freelance": "freelance",
}

SeniorityLevel = Literal[
    "internship",
    "working_student",
    "trainee",
    "junior",
    "entry_level",
    "mid_level",
    "senior",
    "lead",
    "principal",
    "manager",
]

_SENIORITY_LEVEL_ALIASES = {
    "intern": "internship",
    "internship": "internship",
    "working student": "working_student",
    "working_student": "working_student",
    "trainee": "trainee",
    "junior": "junior",
    "entry level": "entry_level",
    "entry_level": "entry_level",
    "mid level": "mid_level",
    "mid_level": "mid_level",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
    "manager": "manager",
}

_LEGACY_SENIORITY_VALUES = {
    "internship",
    "working_student",
    "trainee",
}


class AIWorkflowTrace(BaseModel):
    workflow_name: str
    operation: str
    model: str
    profile_name: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: list[float] = Field(default_factory=list)
    max_tool_calls: int | None = None
    truncation: str = "disabled"
    attempt_count: int = 1
    duration_ms: int | None = None
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CandidateCVIdentity(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""


class CandidateCVExtracted(BaseModel):
    identity: CandidateCVIdentity = Field(default_factory=CandidateCVIdentity)
    work_experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    workflow_trace: AIWorkflowTrace | None = None


class CandidateSupplementalExtracted(BaseModel):
    work_experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    workflow_trace: AIWorkflowTrace | None = None


class CandidatePreferences(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    remote_preference: list[RemotePreference] = Field(default_factory=list)
    employment_type: list[EmploymentType] = Field(default_factory=list)
    seniority_level: list[SeniorityLevel] = Field(default_factory=list)
    availability: str = ""
    salary_min_eur: int | None = None
    salary_max_eur: int | None = None
    work_authorization: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_preference_layout(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        raw_employment_types = _normalize_preference_values(
            data.get("employment_type"),
            _EMPLOYMENT_TYPE_ALIASES,
        )
        raw_seniority_levels = _normalize_preference_values(
            data.get("seniority_level"),
            _SENIORITY_LEVEL_ALIASES,
        )

        migrated_seniority = [
            item for item in raw_employment_types if item in _LEGACY_SENIORITY_VALUES
        ]
        normalized_employment_types = [
            item for item in raw_employment_types if item not in _LEGACY_SENIORITY_VALUES
        ]
        normalized_seniority_levels = _dedupe(
            [*raw_seniority_levels, *migrated_seniority],
        )

        data["employment_type"] = normalized_employment_types
        data["seniority_level"] = normalized_seniority_levels
        return data

    @field_validator("remote_preference", mode="before")
    @classmethod
    def _coerce_remote_preference(
        cls,
        value: object,
    ) -> list[RemotePreference]:
        return _normalize_preference_values(value, _REMOTE_PREFERENCE_ALIASES)

    @field_validator("work_authorization", mode="before")
    @classmethod
    def _coerce_work_authorization(cls, value: object) -> str:
        normalized = _normalize_single_choice(value, _WORK_AUTHORIZATION_ALIASES)
        return normalized or ""

    @field_validator("seniority_level", mode="before")
    @classmethod
    def _coerce_seniority_level(cls, value: object) -> list[SeniorityLevel]:
        return _normalize_preference_values(value, _SENIORITY_LEVEL_ALIASES)

    @field_validator("salary_min_eur", "salary_max_eur", mode="before")
    @classmethod
    def _coerce_salary_value(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            normalized = value.strip().replace(".", "").replace(",", "")
            if not normalized:
                return None
            return int(normalized)
        return None


class CandidateSourceCV(BaseModel):
    file_path: str = ""
    parsed: bool = False


class CandidateOptionalDocument(BaseModel):
    file_path: str = ""
    file_name: str = ""
    document_type: str = "other"
    parsed: bool = False


class CandidateSourceDocuments(BaseModel):
    cv: CandidateSourceCV = Field(default_factory=CandidateSourceCV)
    optional_documents: list[CandidateOptionalDocument] = Field(default_factory=list)

    @field_validator("optional_documents", mode="before")
    @classmethod
    def _coerce_legacy_optional_documents(cls, value: object) -> object:
        if not isinstance(value, list):
            return value

        normalized: list[object] = []
        for item in value:
            if isinstance(item, str):
                normalized.append(
                    {
                        "file_path": item,
                        "file_name": Path(item).name,
                        "document_type": "other",
                        "parsed": False,
                    }
                )
            else:
                normalized.append(item)
        return normalized


class CandidateProfileData(BaseModel):
    profile_status: Literal["draft"] = "draft"
    source_documents: CandidateSourceDocuments = Field(default_factory=CandidateSourceDocuments)
    cv_extracted: CandidateCVExtracted = Field(default_factory=CandidateCVExtracted)
    candidate_preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)


class CandidateProfile(BaseModel):
    candidate_profile: CandidateProfileData = Field(default_factory=CandidateProfileData)


def _normalize_preference_values(
    value: object,
    aliases: dict[str, str],
) -> list[str]:
    if value is None or value == "":
        return []

    if isinstance(value, str):
        raw_values = re.split(r"[,\n;/]+", value)
    elif isinstance(value, list):
        raw_values = value
    else:
        return []

    normalized: list[str] = []
    for raw_value in raw_values:
        item = str(raw_value).strip().lower()
        if not item:
            continue
        canonical = aliases.get(item, item)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _normalize_single_choice(value: object, aliases: dict[str, str]) -> str:
    if value is None:
        return ""
    item = str(value).strip().lower()
    if not item:
        return ""
    return aliases.get(item, item)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


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

    @model_validator(mode="after")
    def _reject_apply_url_that_matches_source_url(self) -> JobListing:
        if self.apply_url is None:
            return self

        if _normalized_url_identity(str(self.apply_url)) == _normalized_url_identity(
            str(self.source_url)
        ):
            raise ValueError(
                "Apply URL must point to the application destination, not the job offer page."
            )
        return self


def _normalized_url_identity(value: str) -> tuple[str, str, str]:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return parsed.scheme.lower(), parsed.netloc.lower(), path


ConfidenceLevel = Literal["high", "medium", "low"]


ApplicationArtifactStatus = Literal[
    "draft",
    "needs_review",
    "approved",
    "rejected",
    "regenerated",
    "manually_edited",
]


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
    review_status: Literal["draft", "reviewed"] = "draft"
    workflow_trace: AIWorkflowTrace | None = None
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


class ApplicationArtifact(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    status: ApplicationArtifactStatus = "draft"
    content: str = ""
    source_prompt: str | None = None
    source_requirement: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationPackage(BaseModel):
    job_id: str
    status: ApplicationArtifactStatus = "draft"
    workflow_trace: AIWorkflowTrace | None = None
    artifacts: list[ApplicationArtifact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    selected_experience_units: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)


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
