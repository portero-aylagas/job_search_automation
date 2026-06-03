"""Enforce Karen's runtime permission rules before tool execution."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel

from src.schemas import AgentJobPermissionGrant


class PermissionLevel(str, Enum):
    """Tool permission level used by Karen's runtime policy."""

    READ_ONLY = "READ_ONLY"
    DRAFT_ONLY = "DRAFT_ONLY"
    MUTATES_LOCAL_STATE = "MUTATES_LOCAL_STATE"
    EXTERNAL_BROWSER_ACTION = "EXTERNAL_BROWSER_ACTION"
    FINAL_SUBMISSION = "FINAL_SUBMISSION"


class KarenPolicyDecision(BaseModel):
    """Policy decision for one proposed Karen tool call."""

    allowed: bool
    permission_level: PermissionLevel
    reason: str = ""


BLOCKED_TOOL_NAMES = {
    "login_automation",
    "captcha_handling",
    "recruiter_messaging",
    "bypass_review_gates",
    "invent_candidate_data",
}

CHAT_BLOCKED_REVIEW_TOOLS = {
    "reject_package",
}

PERMISSION_MANAGEMENT_TOOLS = {
    "grant_job_session_permission",
    "revoke_job_session_permission",
    "inspect_job_session_permission",
}

_EXPLICIT_ACTION_WORDS = {
    "analyze",
    "apply",
    "approve",
    "approval",
    "build",
    "complete",
    "continue",
    "create",
    "delete",
    "discover",
    "draft",
    "generate",
    "go",
    "handle",
    "grant",
    "help",
    "kill",
    "launch",
    "navigate",
    "open",
    "prepare",
    "remove",
    "revoke",
    "review",
    "run",
    "show",
    "start",
    "stop",
    "submit",
    "switch",
    "authorize",
}


def evaluate_karen_tool_request(
    *,
    tool_name: str | None,
    permission_level: PermissionLevel,
    auto_execute: bool,
    user_message: str,
    selected_job_id: str | None = None,
    target_job_id: str | None = None,
    job_permissions: dict[str, AgentJobPermissionGrant] | None = None,
    requires_job_permission: bool = False,
) -> KarenPolicyDecision:
    """Return whether Karen may execute the proposed tool from chat.

    Args:
        tool_name: Proposed tool name from the LLM classifier.
        permission_level: Enforced tool permission from the registry.
        auto_execute: Whether the classifier says the user asked to execute now.
        user_message: Raw user message used to verify explicit intent.
    """

    if not tool_name:
        return KarenPolicyDecision(
            allowed=True,
            permission_level=PermissionLevel.READ_ONLY,
            reason="No tool execution requested.",
        )

    if tool_name in BLOCKED_TOOL_NAMES:
        return KarenPolicyDecision(
            allowed=False,
            permission_level=permission_level,
            reason=_blocked_reason(tool_name),
        )

    if tool_name in CHAT_BLOCKED_REVIEW_TOOLS:
        return KarenPolicyDecision(
            allowed=False,
            permission_level=permission_level,
            reason=(
                "That review or launch step is not available from free-form chat. "
                "Open the Jobs page and use the existing review panel."
            ),
        )

    if permission_level == PermissionLevel.READ_ONLY:
        return KarenPolicyDecision(
            allowed=True,
            permission_level=permission_level,
            reason="Read-only tool execution is allowed.",
        )

    if tool_name.startswith("go_to_") and auto_execute:
        return KarenPolicyDecision(
            allowed=True,
            permission_level=permission_level,
            reason="Route-only tool execution is allowed.",
        )

    if not auto_execute:
        return KarenPolicyDecision(
            allowed=False,
            permission_level=permission_level,
            reason="Karen can run that action only after an explicit request to do it now.",
        )

    if not user_message_has_explicit_action(user_message):
        return KarenPolicyDecision(
            allowed=False,
            permission_level=permission_level,
            reason="The message does not contain an explicit action request.",
        )

    if tool_name not in PERMISSION_MANAGEMENT_TOOLS:
        active_job_id = target_job_id or selected_job_id
        if requires_job_permission and not active_job_id:
            return KarenPolicyDecision(
                allowed=True,
                permission_level=permission_level,
                reason="The tool will ask the user to select a job.",
            )
        grant = _grant_for_job(
            job_permissions or {},
            active_job_id,
        )
        if tool_name == "continue_to_apply_assistance":
            if grant is None or not (
                grant.allow_app_mutations and grant.allow_browser_launch
            ):
                return KarenPolicyDecision(
                    allowed=False,
                    permission_level=permission_level,
                    reason=(
                        "Continue to apply assistance requires a per-job session "
                        "grant with app mutations and Browser Use launch enabled."
                    ),
                )
        if permission_level == PermissionLevel.FINAL_SUBMISSION:
            if "submit" not in user_message.casefold():
                return KarenPolicyDecision(
                    allowed=False,
                    permission_level=permission_level,
                    reason=(
                        "Final submission requires an explicit submit or "
                        "final-submit request."
                    ),
                )
            if grant is None or not grant.allow_final_submission:
                return KarenPolicyDecision(
                    allowed=False,
                    permission_level=permission_level,
                    reason=(
                        "Final application submission requires a per-job session "
                        "grant with final submission enabled."
                    ),
                )
        elif permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION:
            if grant is None or not grant.allow_browser_launch:
                return KarenPolicyDecision(
                    allowed=False,
                    permission_level=permission_level,
                    reason=(
                        "Browser Use launch requires a per-job session grant with "
                        "browser launch enabled."
                    ),
                )
        elif requires_job_permission and permission_level in {
            PermissionLevel.DRAFT_ONLY,
            PermissionLevel.MUTATES_LOCAL_STATE,
        }:
            if grant is None or not grant.allow_app_mutations:
                return KarenPolicyDecision(
                    allowed=False,
                    permission_level=permission_level,
                    reason=(
                        "This job-scoped action requires a per-job Karen session "
                        "grant with app mutations enabled."
                    ),
                )

    if permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION:
        if tool_name not in {
            "prepare_apply_assistance",
            "launch_browser_use",
            "stop_browser_use_session",
            "kill_browser_use_processes",
        }:
            return KarenPolicyDecision(
                allowed=False,
                permission_level=permission_level,
                reason="This Browser Use action is not available from free-form chat.",
            )
        return KarenPolicyDecision(
            allowed=True,
            permission_level=permission_level,
            reason="Explicit Browser Use action is allowed by the selected-job grant.",
        )

    return KarenPolicyDecision(
        allowed=True,
        permission_level=permission_level,
        reason="Explicit local workflow action is allowed.",
    )


def user_message_has_explicit_action(message: str) -> bool:
    """Return whether a message clearly asks Karen to do something now."""

    normalized = message.casefold()
    words = set(re.findall(r"[a-z0-9']+", normalized))
    return bool(words & _EXPLICIT_ACTION_WORDS) or any(
        phrase in normalized for phrase in ("do it", "move me", "take me")
    )


def _blocked_reason(tool_name: str) -> str:
    reasons = {
        "login_automation": "Login automation is out of scope and blocked.",
        "captcha_handling": "Captcha handling is out of scope and blocked.",
        "recruiter_messaging": "Recruiter messaging automation is blocked.",
        "bypass_review_gates": "Karen cannot bypass human review gates.",
        "invent_candidate_data": "Karen cannot invent candidate data or decisions.",
    }
    return reasons.get(tool_name, "This action is blocked by Karen's runtime policy.")


def _grant_for_job(
    job_permissions: dict[str, AgentJobPermissionGrant],
    job_id: str | None,
) -> AgentJobPermissionGrant | None:
    if not job_id:
        return None
    return job_permissions.get(job_id)
