from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_chat import load_agent_chat_messages, load_agent_events
from src.agent_workflow import AgentWorkflowDependencies
from src.agents.karen.graph import process_karen_chat_turn
from src.agents.karen.policy import PermissionLevel
from src.agents.karen.state import (
    KarenContext,
    KarenIntentResponse,
    KarenPermissionGrantIntent,
)
from src.app_workflow import (
    load_application_requirements,
    load_jobs_index,
    save_candidate_profile,
)
from src.application_fill_plan import (
    generate_application_fill_plan,
    load_application_fill_plan,
    save_application_fill_plan,
)
from src.application_package import load_application_package, save_application_package
from src.application_requirements import (
    save_application_page_snapshot,
    save_application_requirements,
)
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import (
    ApplicationArtifact,
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateProfile,
    JobListing,
)
from src.services.karen_permission_service import grant_job_session_permission
from src.tracker_status import archive_tracker_record


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


def grant_full_permission(tmp_path: Path, session_id: str, job_id: str) -> None:
    grant_job_session_permission(
        tmp_path,
        session_id=session_id,
        job_id=job_id,
        allow_app_mutations=True,
        allow_browser_launch=True,
        allow_final_submission=True,
    )


def full_inline_permission_grant() -> KarenPermissionGrantIntent:
    return KarenPermissionGrantIntent(
        grant_selected_job_permissions=True,
        allow_app_mutations=True,
        allow_browser_launch=True,
        allow_final_submission_permission=False,
    )


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


def fake_package_generator(
    _profile: CandidateProfile,
    _units: list,
    job: JobListing,
    _requirements: ApplicationRequirements | None,
) -> ApplicationPackage:
    return ApplicationPackage(
        job_id=job.id,
        status="draft",
        artifacts=[
            ApplicationArtifact(
                id="application-summary",
                type="application_summary",
                label="Application Summary",
                content="Application summary.",
            )
        ],
    )


def fake_fill_plan_generator(
    profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillPlan:
    return generate_application_fill_plan(
        profile,
        requirements,
        package,
        page_snapshot=snapshot,
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
    grant_full_permission(tmp_path, "karen-continue", job.id)

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
    grant_full_permission(tmp_path, "karen-help-apply", job.id)

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


def test_karen_broad_apply_command_starts_browser_use(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-apply-all", job.id)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Do all steps needed to apply.",
        session_id="karen-apply-all",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will continue until Browser Use is ready.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
        dependencies=AgentWorkflowDependencies(
            requirements_discoverer=fake_requirements_discoverer,
            package_generator=fake_package_generator,
            fill_plan_generator=fake_fill_plan_generator,
            browser_launcher=lambda *_args, **_kwargs: "started",
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert result.context.job_permissions[job.id].allow_app_mutations is True
    assert result.context.job_permissions[job.id].allow_browser_launch is True
    assert "Browser Use started" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-apply-all")
    assert [event.action for event in events] == [
        "discover_requirements",
        "review_requirements",
        "generate_package",
        "approve_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
    ]


def test_karen_permissioned_apply_command_continues_past_needs_review_package(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-apply-existing-package", job.id)
    save_application_requirements(
        tmp_path,
        ApplicationRequirements(
            job_id=job.id,
            apply_url=str(job.apply_url),
            source_url=str(job.source_url),
            status="discovered",
            review_status="reviewed",
            job_preserving=True,
        ),
    )
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )
    save_application_package(
        tmp_path,
        ApplicationPackage(
            job_id=job.id,
            status="needs_review",
            artifacts=[
                ApplicationArtifact(
                    id="application-summary",
                    type="application_summary",
                    label="Application Summary",
                    content="Application summary.",
                )
            ],
        ),
        job,
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="do the whole application and apply with Browser Use",
        session_id="karen-apply-existing-package",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will continue the selected application.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
        dependencies=AgentWorkflowDependencies(
            fill_plan_generator=fake_fill_plan_generator,
            browser_launcher=lambda *_args, **_kwargs: "started",
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert "Browser Use started" in result.assistant_message
    assert "package_review" not in result.assistant_message
    events = load_agent_events(tmp_path, "karen-apply-existing-package")
    assert [event.action for event in events] == [
        "approve_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
    ]


def test_karen_permissioned_apply_reviews_default_blocked_fill_plan_fields(
    tmp_path: Path,
) -> None:
    profile, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-apply-blocked-fill-plan", job.id)
    requirements = ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status="discovered",
        review_status="reviewed",
        job_preserving=True,
    )
    save_application_requirements(tmp_path, requirements)
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )
    package = ApplicationPackage(
        job_id=job.id,
        status="approved",
        artifacts=[
            ApplicationArtifact(
                id="application-summary",
                type="application_summary",
                label="Application Summary",
                content="Application summary.",
            )
        ],
    )
    save_application_package(tmp_path, package, job)
    fill_plan = generate_application_fill_plan(profile, requirements, package)
    fill_plan.field_values = []
    fill_plan.blocked_fields = [
        ApplicationFillBlockedField(
            label="Voluntary disability disclosure",
            reason="Requires a personal user decision.",
        )
    ]
    save_application_fill_plan(tmp_path, fill_plan)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message=(
            "do the whole application for this whole. I grant you permission "
            "for all, including reviews and browser use."
        ),
        session_id="karen-apply-blocked-fill-plan",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will continue the selected application.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
                permission_grant=full_inline_permission_grant(),
            )
        ),
        dependencies=AgentWorkflowDependencies(
            browser_launcher=lambda *_args, **_kwargs: "started",
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    assert "Browser Use started" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-apply-blocked-fill-plan")
    assert [event.action for event in events] == [
        "grant_job_session_permission",
        "review_fill_plan",
        "launch_browser_use",
    ]
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "reviewed"
    assert fill_plan.blocked_fields == []
    assert fill_plan.field_values[0].label == "Voluntary disability disclosure"
    assert fill_plan.field_values[0].value == ""


def test_karen_permissioned_apply_routes_to_jobs_for_required_fill_plan_answers(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-apply-needs-answer-fill-plan", job.id)
    save_application_requirements(
        tmp_path,
        ApplicationRequirements(
            job_id=job.id,
            apply_url=str(job.apply_url),
            source_url=str(job.source_url),
            status="discovered",
            review_status="reviewed",
            job_preserving=True,
        ),
    )
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )
    save_application_package(
        tmp_path,
        ApplicationPackage(
            job_id=job.id,
            status="approved",
            artifacts=[
                ApplicationArtifact(
                    id="application-summary",
                    type="application_summary",
                    label="Application Summary",
                    content="Application summary.",
                )
            ],
        ),
        job,
    )
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            needs_answer_fields=[
                ApplicationFillNeedsAnswerField(
                    label="Earliest available start date",
                    reason="Requires a reviewer-supplied answer.",
                    required=True,
                )
            ],
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message=(
            "do the whole application for this whole. I grant you permission "
            "for all, including reviews and browser use."
        ),
        session_id="karen-apply-needs-answer-fill-plan",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will continue the selected application.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
                permission_grant=full_inline_permission_grant(),
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "needs_input"
    assert result.tool_result.route_hint == "Jobs"
    assert "Browser Use cannot start yet" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-apply-needs-answer-fill-plan")
    assert [event.action for event in events] == [
        "grant_job_session_permission",
        "continue_to_apply_assistance",
    ]
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "draft"


@pytest.mark.parametrize(
    ("user_message", "session_id"),
    [
        (
            "apply to this job, you have approval to do whatever is needed",
            "karen-inline-grant-approval",
        ),
        (
            "you have my approval to do everything needed for this job",
            "karen-inline-grant-full-approval",
        ),
        (
            "I authorize Karen to handle all steps for this selected application",
            "karen-inline-grant-authorize",
        ),
        (
            "go ahead with the application and open Browser Use if needed",
            "karen-inline-grant-browser",
        ),
    ],
)
def test_karen_inline_permission_grant_allows_varied_apply_commands(
    tmp_path: Path,
    user_message: str,
    session_id: str,
) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message=user_message,
        session_id=session_id,
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message=(
                    "I can continue with the selected application using the "
                    "permissions you granted."
                ),
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
                permission_grant=full_inline_permission_grant(),
            )
        ),
        dependencies=AgentWorkflowDependencies(
            requirements_discoverer=fake_requirements_discoverer,
            package_generator=fake_package_generator,
            fill_plan_generator=fake_fill_plan_generator,
            browser_launcher=lambda *_args, **_kwargs: "started",
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    grant = result.context.job_permissions[job.id]
    assert grant.allow_app_mutations is True
    assert grant.allow_browser_launch is True
    assert grant.allow_final_submission is False
    assert "Browser Use started" in result.assistant_message
    events = load_agent_events(tmp_path, session_id)
    assert [event.action for event in events] == [
        "grant_job_session_permission",
        "discover_requirements",
        "review_requirements",
        "generate_package",
        "approve_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
    ]


def test_karen_inline_permission_grant_needs_selected_job(tmp_path: Path) -> None:
    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=None,
        user_message="apply to this job, you have approval to do whatever is needed",
        session_id="karen-inline-grant-no-job",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="Select a job first.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
                permission_grant=full_inline_permission_grant(),
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "needs_job"
    assert result.context.job_permissions == {}
    assert "Select a job" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-inline-grant-no-job")
    assert not any(event.action == "grant_job_session_permission" for event in events)


def test_karen_inline_permission_grant_does_not_submit_without_submit_request(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Apply to this job now, you have my approval for all steps.",
        session_id="karen-inline-grant-not-submit",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I can help with the application.",
                proposed_tool="final_submission",
                permission_level=PermissionLevel.FINAL_SUBMISSION,
                auto_execute=True,
                permission_grant=full_inline_permission_grant(),
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "refused"
    grant = result.context.job_permissions[job.id]
    assert grant.allow_final_submission is False
    assert "explicit submit" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-inline-grant-not-submit")
    assert [event.action for event in events] == [
        "grant_job_session_permission",
        "final_submission",
    ]
    assert events[-1].result == "refused"


def test_karen_unstructured_all_wording_does_not_create_inline_grant(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Apply to this job. I grant permission for all.",
        session_id="karen-inline-no-structured-grant",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I can help apply.",
                proposed_tool="continue_to_apply_assistance",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "refused"
    assert result.context.job_permissions == {}
    assert "app mutations and Browser Use launch" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-inline-no-structured-grant")
    assert not any(event.action == "grant_job_session_permission" for event in events)


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
    assert "final submission" in granted.assistant_message

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
    assert "final submission=True" in inspected.assistant_message


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
    assert "session grant" in result.assistant_message


def test_karen_direct_review_requirements_executes_when_saved_data_is_complete(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-review-reqs", job.id)
    save_application_requirements(
        tmp_path,
        ApplicationRequirements(
            job_id=job.id,
            apply_url=str(job.apply_url),
            source_url=str(job.source_url),
            status="discovered",
            review_status="draft",
            job_preserving=True,
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Approve the requirements review.",
        session_id="karen-review-reqs",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will approve the saved requirements.",
                proposed_tool="review_requirements",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    requirements = load_application_requirements(tmp_path, job.id)
    assert requirements is not None
    assert requirements.review_status == "reviewed"
    events = load_agent_events(tmp_path, "karen-review-reqs")
    assert events[-1].action == "review_requirements"
    assert events[-1].result == "executed"


def test_karen_direct_approve_package_executes_when_saved_package_is_reviewable(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-direct-approve-package", job.id)
    save_application_package(
        tmp_path,
        ApplicationPackage(
            job_id=job.id,
            status="draft",
            artifacts=[
                ApplicationArtifact(
                    id="application-summary",
                    type="application_summary",
                    label="Application Summary",
                    content="Application summary.",
                )
            ],
        ),
        job,
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Approve this package now.",
        session_id="karen-direct-approve-package",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will approve the saved package.",
                proposed_tool="approve_package",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    package = load_application_package(tmp_path, job.id)
    assert package is not None
    assert package.status == "approved"


def test_karen_direct_review_fill_plan_uses_default_blocked_values(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-direct-fill-plan-blocked", job.id)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            blocked_fields=[
                ApplicationFillBlockedField(
                    label="Voluntary disability disclosure",
                    reason="Requires a personal user decision.",
                )
            ],
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Review the fill plan now.",
        session_id="karen-direct-fill-plan-blocked",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will review the saved fill plan.",
                proposed_tool="review_fill_plan",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "reviewed"
    assert fill_plan.blocked_fields == []
    assert fill_plan.field_values[0].label == "Voluntary disability disclosure"
    assert fill_plan.field_values[0].value == ""


def test_karen_direct_review_fill_plan_blocks_required_missing_answers(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-direct-fill-plan-needs-answer", job.id)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            needs_answer_fields=[
                ApplicationFillNeedsAnswerField(
                    label="Earliest available start date",
                    reason="Requires a reviewer-supplied answer.",
                    required=True,
                )
            ],
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Review the fill plan now.",
        session_id="karen-direct-fill-plan-needs-answer",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will review the saved fill plan.",
                proposed_tool="review_fill_plan",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "needs_input"
    assert result.tool_result.route_hint == "Jobs"
    assert "fill-plan review" in result.assistant_message
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "draft"


def test_karen_direct_review_fill_plan_blocks_invalid_upload_paths(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-direct-fill-plan-upload", job.id)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            upload_files=[
                ApplicationFillUploadFile(
                    label="CV",
                    file_path="/tmp/unreviewed/cv.pdf",
                    document_type="cv",
                    required=True,
                )
            ],
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Review the fill plan now.",
        session_id="karen-direct-fill-plan-upload",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will review the saved fill plan.",
                proposed_tool="review_fill_plan",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "needs_input"
    assert result.tool_result.route_hint == "Jobs"
    assert "required upload file paths" in result.assistant_message


def test_karen_direct_review_fill_plan_executes_when_complete(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-direct-fill-plan-review", job.id)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            field_values=[
                ApplicationFillFieldValue(
                    label="First name",
                    value="Taylor",
                    required=True,
                )
            ],
        ),
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Review the fill plan now.",
        session_id="karen-direct-fill-plan-review",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will review the saved fill plan.",
                proposed_tool="review_fill_plan",
                permission_level=PermissionLevel.MUTATES_LOCAL_STATE,
                auto_execute=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "executed"
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "reviewed"


def test_karen_browser_stop_and_kill_execute_with_browser_permission(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-browser-control", job.id)

    stopped = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Stop the Browser Use session.",
        session_id="karen-browser-control",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will stop Browser Use.",
                proposed_tool="stop_browser_use_session",
                permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
                auto_execute=True,
            )
        ),
    )
    killed = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Kill Browser Use processes.",
        session_id="karen-browser-control",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will kill Browser Use processes.",
                proposed_tool="kill_browser_use_processes",
                permission_level=PermissionLevel.EXTERNAL_BROWSER_ACTION,
                auto_execute=True,
            )
        ),
    )

    assert stopped.tool_result is not None
    assert stopped.tool_result.status == "executed"
    assert killed.tool_result is not None
    assert killed.tool_result.status == "executed"
    events = load_agent_events(tmp_path, "karen-browser-control")
    assert [event.action for event in events[-2:]] == [
        "stop_browser_use_session",
        "kill_browser_use_processes",
    ]


def test_karen_workflow_blocks_archived_selected_job(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    archive_tracker_record(tmp_path, job.id)
    grant_full_permission(tmp_path, "karen-archived-job", job.id)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="Discover requirements for this archived job.",
        session_id="karen-archived-job",
        intent_classifier=static_intent(
            KarenIntentResponse(
                assistant_message="I will discover requirements.",
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
    assert result.tool_result.status == "error"
    assert "Restore this archived job" in result.assistant_message
    assert load_application_requirements(tmp_path, job.id) is None


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
    assert "final submission enabled" in result.assistant_message
    events = load_agent_events(tmp_path, "karen-submit")
    assert events[0].result == "refused"


def test_karen_can_delete_selected_job_from_chat(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    grant_full_permission(tmp_path, "karen-delete-job", job.id)

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
