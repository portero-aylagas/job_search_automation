from __future__ import annotations

from pathlib import Path

from src.agent_chat import load_agent_chat_messages, load_agent_events
from src.agent_workflow import AgentWorkflowDependencies
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.policy import PermissionLevel
from src.agents.karen.state import KarenContext, KarenIntentResponse
from src.app_workflow import save_candidate_profile
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import ApplicationPageSnapshot, ApplicationRequirements, CandidateProfile


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


def fake_requirements_discoverer(job):
    return {
        "job": job,
        "snapshot": ApplicationPageSnapshot(
            requested_url=str(job.apply_url),
            final_url=str(job.apply_url),
        ),
        "requirements": ApplicationRequirements(
            job_id=job.id,
            apply_url=str(job.apply_url),
            source_url=str(job.source_url),
            status="discovered",
            review_status="draft",
            job_preserving=True,
        ),
    }


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


def test_karen_continue_runs_safe_workflow_until_next_gate(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Continue this workflow.",
        session_id="karen-continue",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will continue until a gate.",
                proposed_tool="continue_workflow_until_next_gate",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
        dependencies=AgentWorkflowDependencies(
            requirements_discoverer=fake_requirements_discoverer,
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert "requirements_review" in result.tool_result.message
    events = load_agent_events(tmp_path, "karen-continue")
    assert any(event.action == "discover_requirements" for event in events)


def test_karen_can_start_requirements_for_known_job(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Help me apply to this job.",
        session_id="karen-help-apply",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I can start by discovering application requirements.",
                proposed_tool="discover_requirements",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
        dependencies=AgentWorkflowDependencies(
            requirements_discoverer=fake_requirements_discoverer,
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert "requirements_review" in result.assistant_message


def test_karen_explains_match_analysis_is_not_active_workflow(tmp_path: Path) -> None:
    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=None,
        user_message="What is match analysis?",
        session_id="karen-match-analysis",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message=(
                    "Match analysis is not part of the current known-job apply "
                    "workflow. For a saved job, start with requirements discovery."
                )
            )
        ),
    )

    assert result.tool_result is None
    assert "not part of the current known-job apply workflow" in result.assistant_message


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


def test_karen_refuses_direct_package_approval_tool_from_chat(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Agent",
        selected_job_id=job.id,
        user_message="Approve this package.",
        session_id="karen-approve-direct",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="Package approval stays in the Jobs review panel.",
                proposed_tool="approve_package",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "refused"
    assert "Jobs page" in result.assistant_message


def test_karen_refuses_final_submission_and_logs_it(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Submit the application.",
        session_id="karen-submit",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I cannot submit applications.",
                proposed_tool="final_submission",
                permission_level=PermissionLevel.FINAL_SUBMISSION,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "refused"
    assert "Final application submission" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-submit")
    assert events[0].result == "refused"


def test_karen_missing_openai_key_preserves_transcript(
    tmp_path: Path,
    monkeypatch,
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
    messages = load_agent_chat_messages(tmp_path, "karen-no-key")
    assert [message.role for message in messages] == ["user", "assistant"]
    assert "OPENAI_API_KEY" in messages[-1].content
