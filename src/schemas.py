"""Pydantic schemas for candidate, job, requirements, package, and tracker data."""

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
    """Metadata captured for an AI-assisted workflow call."""

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
    """Identity and contact fields extracted from a candidate CV."""

    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    salutation: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    street_address: str = ""
    street_number: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""
    nationality: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_identity_layout(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        first_name = _normalize_text_value(data.get("first_name"))
        last_name = _normalize_text_value(data.get("last_name"))
        full_name = _normalize_text_value(data.get("full_name"))

        if full_name and (not first_name or not last_name):
            split_first, split_last = _split_full_name_value(full_name)
            data["first_name"] = first_name or split_first
            data["last_name"] = last_name or split_last
        if not full_name and (first_name or last_name):
            data["full_name"] = " ".join(item for item in (first_name, last_name) if item)

        return data

    @field_validator(
        "full_name",
        "first_name",
        "last_name",
        "salutation",
        "location",
        "street_address",
        "street_number",
        "postal_code",
        "city",
        "country",
        "nationality",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        mode="before",
    )
    @classmethod
    def _normalize_text_field(cls, value: object) -> str:
        return _normalize_text_value(value)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> str:
        return _normalize_email_value(value)

    @field_validator("phone", mode="before")
    @classmethod
    def _normalize_phone(cls, value: object) -> str:
        return _normalize_phone_value(value)

    @model_validator(mode="after")
    def _sync_full_name(self) -> CandidateCVIdentity:
        if not self.full_name and (self.first_name or self.last_name):
            self.full_name = " ".join(
                item for item in (self.first_name, self.last_name) if item
            )
        return self


class CandidateCVExtracted(BaseModel):
    """Structured candidate evidence extracted from the primary CV."""

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
    """Structured evidence extracted from optional supporting documents."""

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
    """Manual job-search preferences not reliably inferred from a CV."""

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
    """Stored CV upload metadata for the candidate profile."""

    file_path: str = ""
    parsed: bool = False


class CandidateOptionalDocument(BaseModel):
    """Stored optional supporting-document metadata."""

    file_path: str = ""
    file_name: str = ""
    document_type: str = "other"
    parsed: bool = False


class CandidateSourceDocuments(BaseModel):
    """Uploaded source documents attached to a candidate profile."""

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
    """Top-level candidate profile payload persisted to JSON."""

    profile_status: Literal["draft"] = "draft"
    source_documents: CandidateSourceDocuments = Field(default_factory=CandidateSourceDocuments)
    cv_extracted: CandidateCVExtracted = Field(default_factory=CandidateCVExtracted)
    candidate_preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)


class CandidateProfile(BaseModel):
    """Wrapper model for the persisted candidate profile document."""

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


def _normalize_text_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_email_value(value: object) -> str:
    return _normalize_text_value(value).lower()


def _normalize_phone_value(value: object) -> str:
    raw_value = _normalize_text_value(value)
    if not raw_value:
        return ""

    normalized = re.sub(r"[^\d+]", "", raw_value)
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    if normalized.count("+") > 1:
        normalized = normalized.replace("+", "")
    if "+" in normalized and not normalized.startswith("+"):
        normalized = normalized.replace("+", "")
    return normalized


def _split_full_name_value(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


class ExperienceUnit(BaseModel):
    """Reusable candidate evidence block for matching and package generation."""

    id: str
    title: str
    organization: str
    date_range: str
    summary: str
    skills: list[str] = Field(default_factory=list)
    evidence_points: list[str] = Field(default_factory=list)


ConfidenceLevel = Literal["high", "medium", "low"]

_STORAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_storage_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    if normalized != value or not normalized:
        raise ValueError(f"{field_name} must be a non-empty storage identifier.")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"{field_name} must not contain path separators.")
    if not _STORAGE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} contains unsupported characters.")
    return normalized


class JobDynamicField(BaseModel):
    """Flexible normalized job detail preserved outside fixed schema fields."""

    dynamic: bool = True
    name: str = Field(default="", validate_default=True)
    value: Any
    category: str = ""
    source_text: str = ""
    confidence: ConfidenceLevel = "medium"

    @field_validator("dynamic")
    @classmethod
    def _require_dynamic_marker(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Dynamic job detail fields must have dynamic=true.")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_required_name(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("Dynamic job detail fields require a name.")
        return normalized

    @field_validator("category", "source_text", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str:
        return str(value or "").strip()


class JobListing(BaseModel):
    """Normalized job offer reviewed by the user and stored per job workspace."""

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

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _validate_storage_identifier(value, "Job ID")

    @field_validator("job_details", mode="before")
    @classmethod
    def _normalize_job_details(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Job details must be an object.")

        details = dict(value)
        dynamic_fields = details.get("dynamic_fields")
        if dynamic_fields is None:
            return details
        if not isinstance(dynamic_fields, list):
            raise ValueError("Job details dynamic_fields must be a list.")

        details["dynamic_fields"] = [
            JobDynamicField.model_validate(field).model_dump(mode="json")
            for field in dynamic_fields
        ]
        return details

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


ApplicationArtifactStatus = Literal[
    "draft",
    "needs_review",
    "approved",
    "rejected",
    "regenerated",
    "manually_edited",
]


class ApplicationRequirementFinding(BaseModel):
    """Evidence-backed requirement discovered from an application page."""

    label: str
    required: bool = False
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"
    constraints: list[str] = Field(default_factory=list)


class ApplicationScreeningQuestion(BaseModel):
    """Screening question discovered from an application page."""

    question: str
    required: bool = False
    input_type: str = ""
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"


class ApplicationFormField(BaseModel):
    """Application form field that may require candidate-provided input."""

    name: str = ""
    label: str
    required: bool = False
    input_type: str = ""
    options: list[str] = Field(default_factory=list)
    evidence: str = ""
    confidence: ConfidenceLevel = "medium"


class ApplicationPageControl(BaseModel):
    """Raw page control captured during application-page inspection."""

    kind: str = ""
    name: str = ""
    label: str = ""
    input_type: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""


class ApplicationPageFormSummary(BaseModel):
    """Parsed form summary from an inspected application page."""

    action: str = ""
    method: str = "get"
    labels: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    controls: list[ApplicationPageControl] = Field(default_factory=list)


class ApplicationPageSnapshot(BaseModel):
    """Read-only evidence snapshot collected from an application page."""

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
    """Interpreted application requirements for one job application page."""

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

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        return _validate_storage_identifier(value, "Job ID")


class ApplicationArtifact(BaseModel):
    """Generated or manually edited artifact within an application package."""

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
    """Generated application package with artifacts and review metadata."""

    job_id: str
    status: ApplicationArtifactStatus = "draft"
    workflow_trace: AIWorkflowTrace | None = None
    artifacts: list[ApplicationArtifact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    selected_experience_units: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        return _validate_storage_identifier(value, "Job ID")


ApplicationFillPlanReviewStatus = Literal["draft", "reviewed"]
ApplicationFillEvidenceSource = Literal[
    "control_label",
    "form_label",
    "evidence_match",
    "visible_text_excerpt",
    "raw_html_excerpt",
    "interpreted_only",
]
ApplicationFillEvidenceStatus = Literal[
    "literal_verified",
    "partial_match",
    "interpreted_only",
]


class ApplicationFillFieldValue(BaseModel):
    """Reviewed field value that Browser Use may fill."""

    label: str
    value: str
    name: str = ""
    required: bool = False
    input_type: str = ""
    options: list[str] = Field(default_factory=list)
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    literal_evidence: list[str] = Field(default_factory=list)
    evidence_source: ApplicationFillEvidenceSource = "interpreted_only"
    evidence_status: ApplicationFillEvidenceStatus = "interpreted_only"


class ApplicationFillUploadFile(BaseModel):
    """Reviewed upload file that Browser Use may upload."""

    label: str
    file_path: str
    document_type: str = "other"
    required: bool = False
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    literal_evidence: list[str] = Field(default_factory=list)
    evidence_source: ApplicationFillEvidenceSource = "interpreted_only"
    evidence_status: ApplicationFillEvidenceStatus = "interpreted_only"


class ApplicationFillBlockedField(BaseModel):
    """Application field that Browser Use must not fill automatically."""

    label: str
    reason: str
    name: str = ""
    required: bool = False
    input_type: str = ""
    options: list[str] = Field(default_factory=list)
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    literal_evidence: list[str] = Field(default_factory=list)
    evidence_source: ApplicationFillEvidenceSource = "interpreted_only"
    evidence_status: ApplicationFillEvidenceStatus = "interpreted_only"


class ApplicationFillNeedsAnswerField(BaseModel):
    """Known safe application field that needs a reviewer-supplied answer."""

    label: str
    name: str = ""
    required: bool = False
    input_type: str = ""
    options: list[str] = Field(default_factory=list)
    reason: str
    source: str = ""
    confidence: ConfidenceLevel = "medium"
    literal_evidence: list[str] = Field(default_factory=list)
    evidence_source: ApplicationFillEvidenceSource = "interpreted_only"
    evidence_status: ApplicationFillEvidenceStatus = "interpreted_only"


class ApplicationFillPlan(BaseModel):
    """Reviewed fill contract passed to Browser Use apply assistance."""

    job_id: str
    apply_url: HttpUrl
    review_status: ApplicationFillPlanReviewStatus = "draft"
    field_values: list[ApplicationFillFieldValue] = Field(default_factory=list)
    upload_files: list[ApplicationFillUploadFile] = Field(default_factory=list)
    needs_answer_fields: list[ApplicationFillNeedsAnswerField] = Field(
        default_factory=list
    )
    blocked_fields: list[ApplicationFillBlockedField] = Field(default_factory=list)
    submit_guard_labels: list[str] = Field(default_factory=list)

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        return _validate_storage_identifier(value, "Job ID")


class TrackerRecord(BaseModel):
    """Application tracker row for a saved job."""

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

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        return _validate_storage_identifier(value, "Job ID")
