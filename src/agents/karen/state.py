"""Structured state models for Karen's runtime chat controller."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.agents.karen.policy import PermissionLevel
from src.schemas import AgentJobPermissionGrant


class KarenPermissionGrantIntent(BaseModel):
    """Structured intent to grant selected-job permissions for this session."""

    grant_selected_job_permissions: bool = False
    allow_app_mutations: bool = False
    allow_browser_launch: bool = False
    allow_final_submission_permission: bool = False


class KarenIntentResponse(BaseModel):
    """Structured LLM response for one Karen chat turn."""

    assistant_message: str
    proposed_tool: str | None = None
    permission_level: PermissionLevel = PermissionLevel.READ_ONLY
    auto_execute: bool = False
    target_job_id: str | None = None
    route_page: str | None = None
    permission_grant: KarenPermissionGrantIntent | None = None
    safety_reason: str = ""

    @field_validator("proposed_tool", "target_job_id", "route_page", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class KarenContext(BaseModel):
    """Current app context supplied to Karen before classifying a chat turn."""

    session_id: str
    current_page: str
    selected_job_id: str | None = None
    profile_status_summary: str = ""
    tracker_summary: dict[str, int | str] = Field(default_factory=dict)
    artifact_presence: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    pending_gate: str | None = None
    next_allowed_actions: list[str] = Field(default_factory=list)
    recent_transcript_summary: str = ""
    job_permissions: dict[str, AgentJobPermissionGrant] = Field(default_factory=dict)

    @field_validator("selected_job_id", mode="before")
    @classmethod
    def _blank_job_id_to_none(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class KarenToolResult(BaseModel):
    """Result from executing one Karen tool."""

    tool_name: str
    status: str
    message: str
    artifact_paths: list[str] = Field(default_factory=list)
    route_hint: str | None = None
    event_details: dict[str, object] = Field(default_factory=dict)


class KarenChatTurnResult(BaseModel):
    """Persisted assistant response and optional tool result for a chat turn."""

    assistant_message: str
    intent: KarenIntentResponse | None = None
    tool_result: KarenToolResult | None = None
    context: KarenContext
