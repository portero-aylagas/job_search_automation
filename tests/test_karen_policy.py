from __future__ import annotations

from src.agents.karen.policy import (
    PermissionLevel,
    evaluate_karen_tool_request,
)
from src.agents.karen.tools import KAREN_TOOL_REGISTRY
from src.schemas import AgentJobPermissionGrant


def test_karen_policy_allows_read_only_without_auto_execute() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="list_next_actions",
        permission_level=PermissionLevel.READ_ONLY,
        auto_execute=False,
        user_message="What should I do next?",
    )

    assert decision.allowed is True


def test_karen_policy_requires_explicit_intent_for_local_actions() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        auto_execute=False,
        user_message="Can a package be generated?",
    )

    assert decision.allowed is False
    assert "explicit request" in decision.reason

    blocked_without_grant = evaluate_karen_tool_request(
        tool_name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        auto_execute=True,
        user_message="Generate the application package now.",
        selected_job_id="job-1",
        job_permissions={},
        requires_job_permission=True,
    )

    assert blocked_without_grant.allowed is False
    assert "session grant" in blocked_without_grant.reason

    allowed = evaluate_karen_tool_request(
        tool_name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        auto_execute=True,
        user_message="Generate the application package now.",
        selected_job_id="job-1",
        job_permissions={"job-1": AgentJobPermissionGrant(allow_app_mutations=True)},
        requires_job_permission=True,
    )
    assert allowed.allowed is True


def test_karen_policy_allows_explicit_delete_job_request() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="delete_job_data",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        auto_execute=True,
        user_message="Delete this job data now.",
        selected_job_id="job-1",
        job_permissions={"job-1": AgentJobPermissionGrant(allow_app_mutations=True)},
        requires_job_permission=True,
    )

    assert decision.allowed is True


def test_karen_policy_grant_is_job_scoped() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="generate_application_package",
        permission_level=PermissionLevel.DRAFT_ONLY,
        auto_execute=True,
        user_message="Generate the application package now.",
        selected_job_id="job-2",
        job_permissions={"job-1": AgentJobPermissionGrant(allow_app_mutations=True)},
        requires_job_permission=True,
    )

    assert decision.allowed is False
    assert "session grant" in decision.reason


def test_karen_policy_blocks_review_gate_actions_from_chat() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="approve_package",
        permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
        auto_execute=True,
        user_message="Approve this package.",
        selected_job_id="job-1",
        job_permissions={},
        requires_job_permission=True,
    )

    assert decision.allowed is False
    assert "session grant" in decision.reason


def test_karen_policy_blocks_browser_use_launch_from_chat() -> None:
    decision = evaluate_karen_tool_request(
        tool_name="launch_browser_use",
        permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
        auto_execute=True,
        user_message="Launch Browser Use now.",
    )

    assert decision.allowed is False
    assert "Browser Use launch" in decision.reason


def test_karen_policy_blocks_final_submission_and_unsafe_actions() -> None:
    final_submission = evaluate_karen_tool_request(
        tool_name="final_submission",
        permission_level=PermissionLevel.FINAL_SUBMISSION,
        auto_execute=True,
        user_message="Submit the application now.",
        selected_job_id="job-1",
        job_permissions={"job-1": AgentJobPermissionGrant(allow_app_mutations=True)},
        requires_job_permission=True,
    )
    assert final_submission.allowed is False
    assert "final submission enabled" in final_submission.reason

    allowed_final_submission = evaluate_karen_tool_request(
        tool_name="final_submission",
        permission_level=PermissionLevel.FINAL_SUBMISSION,
        auto_execute=True,
        user_message="Submit the application now.",
        selected_job_id="job-1",
        job_permissions={
            "job-1": AgentJobPermissionGrant(
                allow_app_mutations=True,
                allow_browser_launch=True,
                allow_final_submission=True,
            )
        },
        requires_job_permission=True,
    )
    assert allowed_final_submission.allowed is True

    for tool_name in (
        "login_automation",
        "captcha_handling",
        "recruiter_messaging",
        "bypass_review_gates",
        "invent_candidate_data",
    ):
        decision = evaluate_karen_tool_request(
            tool_name=tool_name,
            permission_level=PermissionLevel.FINAL_SUBMISSION,
            auto_execute=True,
            user_message="Do it now.",
        )

        assert decision.allowed is False


def test_karen_runtime_registry_excludes_match_analysis_actions() -> None:
    assert "analyze_match" not in KAREN_TOOL_REGISTRY
    assert "review_match" not in KAREN_TOOL_REGISTRY
    assert "reject_match" not in KAREN_TOOL_REGISTRY
