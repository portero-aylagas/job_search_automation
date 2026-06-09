from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_chat import load_agent_chat_messages
from src.agents.karen.graph import _karen_trace_display_name, process_karen_chat_turn
from src.agents.karen.policy import PermissionLevel
from src.agents.karen.state import KarenContext, KarenIntentResponse
from src.app_workflow import load_jobs_index, save_candidate_profile
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import CandidateProfile
from src.services.karen_permission_service import grant_job_session_permission


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {"cv": {"file_path": "/tmp/cv.pdf", "parsed": True}},
                "cv_extracted": {
                    "identity": {
                        "first_name": "Taylor",
                        "last_name": "Rivera",
                        "gender": "Female",
                        "email": "taylor@example.com",
                        "phone": "+49170123456",
                        "street_address": "Example Street",
                        "street_number": "12",
                        "postal_code": "10115",
                        "city": "Berlin",
                        "country": "Germany",
                        "nationality": "Spanish",
                    },
                    "skills": ["Python", "SQL", "Workflow automation"],
                },
                "candidate_preferences": {
                    "target_roles": ["Automation Engineer"],
                    "target_locations": ["Berlin"],
                    "remote_preference": ["hybrid"],
                    "employment_type": ["full_time"],
                    "seniority_level": ["mid_level"],
                    "availability": "Immediately",
                    "salary_min_eur": 55000,
                    "salary_max_eur": 70000,
                    "work_authorization": "eu_authorized",
                },
            }
        }
    )


def make_job():
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        location="Berlin",
        remote_policy="Hybrid",
        description="Build workflow automation tools.",
        requirements=["Python", "SQL", "Workflow automation"],
    )


def setup_profile_and_job(tmp_path: Path):
    profile = make_profile()
    job = make_job()
    save_candidate_profile(tmp_path, profile)
    persist_job_listing(tmp_path, job)
    return profile, job


def static_intent(intent: KarenIntentResponse):
    def classify(_context: KarenContext, _message: str) -> KarenIntentResponse:
        return intent

    return classify


def test_karen_trace_display_name_includes_page_and_job() -> None:
    assert (
        _karen_trace_display_name(current_page="Jobs", selected_job_id="job-123")
        == "Karen: Jobs / job-123"
    )


def test_karen_explains_app_without_tool_execution(tmp_path: Path) -> None:
    result = process_karen_chat_turn(
        tmp_path,
        current_page="Candidate Profile",
        selected_job_id=None,
        user_message="What is this app?",
        session_id="karen-explain-app",
        intent_classifier=static_intent(
            KarenIntentResponse(assistant_message="This app builds reviewable packages.")
        ),
    )

    assert result.tool_result is None
    assert "reviewable packages" in result.assistant_message
    messages = load_agent_chat_messages(tmp_path, "karen-explain-app")
    assert [message.role for message in messages] == ["user", "assistant"]


def test_karen_explains_own_role_with_read_only_tool(tmp_path: Path) -> None:
    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=None,
        user_message="What do you do, Karen?",
        session_id="karen-role",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I can explain my role.",
                proposed_tool="explain_karen",
                permission_level=PermissionLevel.READ_ONLY,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "answered"
    assert "I am Karen" in result.assistant_message
    assert "final submission" in result.assistant_message


def test_karen_lists_next_actions_from_current_state(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="What should I do next?",
        session_id="karen-next",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="Here is the next action.",
                proposed_tool="list_next_actions",
                permission_level=PermissionLevel.READ_ONLY,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert "Discover application requirements" in result.assistant_message


def test_karen_permission_tool_grants_selected_job_session(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    granted = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=job.id,
        user_message="Grant Karen permission for this job now.",
        session_id="karen-grant",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will grant this session permission.",
                proposed_tool="grant_job_session_permission",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert granted.tool_result is not None
    assert granted.tool_result.status == "executed"
    assert "Browser Use launch" in granted.assistant_message
    assert "final submission" not in granted.assistant_message.casefold()

    inspected = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=job.id,
        user_message="Inspect Karen permission.",
        session_id="karen-grant",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will inspect permission.",
                proposed_tool="inspect_job_session_permission",
                permission_level=PermissionLevel.READ_ONLY,
                auto_execute=True,
            )
        ),
    )

    assert inspected.tool_result is not None
    assert inspected.tool_result.status == "answered"
    assert "Browser Use launch=True" in inspected.assistant_message
    assert "final submission" not in inspected.assistant_message.casefold()


def test_karen_routes_package_approval_to_jobs(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=job.id,
        user_message="Approve this package.",
        session_id="karen-approve-route",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="Package approval stays in the Jobs review panel.",
                proposed_tool="go_to_jobs",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
                route_page="Jobs",
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.route_hint == "Jobs"
    assert result.tool_result.status == "routed"


@pytest.mark.parametrize(
    "tool_name",
    [
        "discover_requirements",
        "review_requirements",
        "generate_application_package",
        "review_application_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
        "final_submission",
    ],
)
def test_karen_rejects_legacy_direct_workflow_tools(
    tmp_path: Path,
    tool_name: str,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_job_session_permission(
        tmp_path,
        session_id="karen-legacy-direct",
        job_id=job.id,
        allow_app_mutations=True,
        allow_browser_launch=True,
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message=f"Run {tool_name}.",
        session_id="karen-legacy-direct",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="Trying a legacy direct workflow tool.",
                proposed_tool=tool_name,
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "error"
    assert "registered tool" in result.assistant_message


def test_karen_refuses_blocked_runtime_tools(tmp_path: Path) -> None:
    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=None,
        user_message="Invent missing candidate data now.",
        session_id="karen-blocked-tool",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I cannot invent data.",
                proposed_tool="invent_candidate_data",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "refused"
    assert "invent candidate data" in result.assistant_message.casefold()


def test_karen_can_delete_selected_job_from_chat(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_job_session_permission(
        tmp_path,
        session_id="karen-delete-job",
        job_id=job.id,
        allow_app_mutations=True,
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=job.id,
        user_message="Delete this job data now.",
        session_id="karen-delete-job",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will delete this job data.",
                proposed_tool="delete_job_data",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert "Deleted local data" in result.assistant_message
    assert load_jobs_index(tmp_path) == []
    assert not (tmp_path / "data" / "runtime" / "jobs" / job.id).exists()


def test_karen_missing_openai_key_preserves_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Tracker",
        selected_job_id=None,
        user_message="What is this app?",
        session_id="karen-no-key",
    )

    assert "OPENAI_API_KEY" in result.assistant_message
    assert "Selected job: None" in result.assistant_message
    assert "Next allowed actions" not in result.assistant_message
    messages = load_agent_chat_messages(tmp_path, "karen-no-key")
    assert [message.role for message in messages] == ["user", "assistant"]
    assert "OPENAI_API_KEY" in messages[-1].content
