"""Enforce Karen's runtime permission rules before tool execution."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


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
    "final_submission",
    "login_automation",
    "captcha_handling",
    "recruiter_messaging",
    "bypass_review_gates",
    "invent_candidate_data",
}

CHAT_BLOCKED_REVIEW_TOOLS = {
    "review_requirements",
    "approve_package",
    "reject_package",
    "review_fill_plan",
    "launch_browser_use",
}

_EXPLICIT_ACTION_WORDS = {
    "analyze",
    "apply",
    "build",
    "continue",
    "create",
    "delete",
    "discover",
    "draft",
    "generate",
    "go",
    "help",
    "navigate",
    "open",
    "prepare",
    "remove",
    "run",
    "show",
    "start",
    "switch",
}


def evaluate_karen_tool_request(
    *,
    tool_name: str | None,
    permission_level: PermissionLevel,
    auto_execute: bool,
    user_message: str,
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

    if tool_name in BLOCKED_TOOL_NAMES or permission_level == PermissionLevel.FINAL_SUBMISSION:
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

    if permission_level == PermissionLevel.EXTERNAL_BROWSER_ACTION:
        if tool_name != "prepare_apply_assistance":
            return KarenPolicyDecision(
                allowed=False,
                permission_level=permission_level,
                reason="Browser Use launch is never auto-executed from chat.",
            )
        return KarenPolicyDecision(
            allowed=True,
            permission_level=permission_level,
            reason="Preparing apply assistance is allowed; launching Browser Use is not.",
        )

    return KarenPolicyDecision(
        allowed=True,
        permission_level=permission_level,
        reason="Explicit local workflow action is allowed.",
    )


def user_message_has_explicit_action(message: str) -> bool:
    """Return whether a message clearly asks Karen to do something now."""

    normalized = message.casefold()
    return any(word in normalized.split() for word in _EXPLICIT_ACTION_WORDS) or any(
        phrase in normalized for phrase in ("do it", "move me", "take me")
    )


def _blocked_reason(tool_name: str) -> str:
    reasons = {
        "final_submission": "Final application submission is always blocked.",
        "login_automation": "Login automation is out of scope and blocked.",
        "captcha_handling": "Captcha handling is out of scope and blocked.",
        "recruiter_messaging": "Recruiter messaging automation is blocked.",
        "bypass_review_gates": "Karen cannot bypass human review gates.",
        "invent_candidate_data": "Karen cannot invent candidate data or decisions.",
    }
    return reasons.get(tool_name, "This action is blocked by Karen's runtime policy.")
