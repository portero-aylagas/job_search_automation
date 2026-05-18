from __future__ import annotations

from typing import Literal

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
    location: str
    remote_policy: str | None = None
    apply_url: HttpUrl | None = None
    description: str
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    salary: str | None = None
    posted_date: str | None = None
    source: str
    retrieval_mode: str


class TrackerRecord(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    source: str
    retrieval_mode: str
    match_score: float | None = None
    status: TrackerStatus = "new"
    notes: str | None = None
    generated_package_path: str | None = None
