from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent_chat import load_agent_events
from src.agents.karen.graph import (
    classify_karen_workflow_intent_with_llm,
    process_karen_chat_turn,
)
from src.agents.karen.state import KarenIntentResponse
from src.app_workflow import load_application_requirements, save_candidate_profile
from src.application_fill_plan import (
    generate_application_fill_plan,
    load_application_fill_plan,
    mark_application_fill_plan_reviewed,
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
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateProfile,
)
from src.services import job_workflow_service as job_services
from src.workflow.workflow_executor import run_karen_workflow_goal
from src.workflow.workflow_planner import WorkflowIntent, planner_next_action
from src.workflow.workflow_state import CurrentWorkflowState, load_current_workflow_state


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


def make_requirements(job, *, reviewed: bool = False) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status="discovered",
        review_status="reviewed" if reviewed else "draft",
        job_preserving=True,
    )


def make_package(job, *, status: str = "draft") -> ApplicationPackage:
    return ApplicationPackage(
        job_id=job.id,
        status=status,
        artifacts=[
            ApplicationArtifact(
                id="application-summary",
                type="application_summary",
                label="Application Summary",
                content="Application summary.",
            )
        ],
    )


def workflow_intent(**overrides: object) -> WorkflowIntent:
    payload = {
        "goal": "continue_until_blocked",
        "allow_draft_generation": True,
        "allow_local_mutations": True,
        "allow_review_gate_crossing": False,
        "allow_browser_launch": False,
        "execution_mode": "manual",
    }
    payload.update(overrides)
    return WorkflowIntent.model_validate(payload)


def static_workflow_intent(intent: WorkflowIntent):
    def classify(_context, _message: str) -> KarenIntentResponse:
        return KarenIntentResponse(
            assistant_message="I will run the workflow controller.",
            workflow_intent=intent,
        )

    return classify


def save_reviewed_requirements(tmp_path: Path, job) -> None:
    save_application_requirements(tmp_path, make_requirements(job, reviewed=True))
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )


def save_reviewed_fill_plan(tmp_path: Path, profile: CandidateProfile, job) -> None:
    requirements = load_application_requirements(tmp_path, job.id)
    package = load_application_package(tmp_path, job.id)
    assert requirements is not None
    assert package is not None
    fill_plan = generate_application_fill_plan(profile, requirements, package)
    save_application_fill_plan(tmp_path, mark_application_fill_plan_reviewed(fill_plan))


def test_llm_classifier_returns_structured_workflow_intent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_parse_structured_response(**kwargs):
        captured.update(kwargs)
        return WorkflowIntent(
            goal="apply_without_browser_use",
            allow_draft_generation=True,
            execution_mode="manual",
        )

    monkeypatch.setattr(
        "src.llm_client.parse_structured_response",
        fake_parse_structured_response,
    )
    intent = classify_karen_workflow_intent_with_llm(
        context=_minimal_karen_context(),
        user_message="apply to this job but do not use browser use",
    )

    assert intent.goal == "apply_without_browser_use"
    assert intent.execution_mode == "manual"
    assert intent.allow_browser_launch is False
    assert captured["text_format"] is WorkflowIntent
    prompt_text = captured["input"][1]["content"]
    assert "do not select python functions" in prompt_text.casefold()


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "generate application data",
            {
                "goal": "generate_application_data",
                "allow_draft_generation": True,
                "execution_mode": "manual",
            },
        ),
        (
            "prepare the package for this job",
            {
                "goal": "generate_application_data",
                "allow_draft_generation": True,
                "execution_mode": "manual",
            },
        ),
        (
            "create the application material",
            {
                "goal": "generate_application_data",
                "allow_draft_generation": True,
                "execution_mode": "manual",
            },
        ),
        (
            "mark application data as reviewed",
            {
                "goal": "mark_current_gate_reviewed",
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "I checked the current review step, mark it reviewed",
            {
                "goal": "mark_current_gate_reviewed",
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "approve the package because I reviewed it",
            {
                "goal": "mark_current_gate_reviewed",
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "generate application data and I give you permission to mark it as reviewed",
            {
                "goal": "generate_and_review_application_data",
                "allow_draft_generation": True,
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "create the package and approve it if it is valid",
            {
                "goal": "generate_and_review_application_data",
                "allow_draft_generation": True,
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "prepare it and you may cross the review gate",
            {
                "goal": "generate_and_review_application_data",
                "allow_draft_generation": True,
                "allow_review_gate_crossing": True,
                "execution_mode": "manual",
            },
        ),
        (
            "apply to this job and use browser use",
            {
                "goal": "launch_browser_application",
                "allow_draft_generation": True,
                "allow_browser_launch": True,
                "execution_mode": "browser_use",
            },
        ),
        (
            "use browser automation for this application",
            {
                "goal": "launch_browser_application",
                "allow_browser_launch": True,
                "execution_mode": "browser_use",
            },
        ),
        (
            "open the browser agent",
            {
                "goal": "launch_browser_application",
                "allow_browser_launch": True,
                "execution_mode": "browser_use",
            },
        ),
        (
            "apply to this job but do not use browser use",
            {
                "goal": "apply_without_browser_use",
                "allow_draft_generation": True,
                "allow_browser_launch": False,
                "execution_mode": "manual",
            },
        ),
        (
            "prepare this manually",
            {
                "goal": "prepare_manual_application",
                "allow_draft_generation": True,
                "allow_browser_launch": False,
                "execution_mode": "manual",
            },
        ),
        (
            "I will apply myself, just prepare the data",
            {
                "goal": "prepare_manual_application",
                "allow_draft_generation": True,
                "allow_browser_launch": False,
                "execution_mode": "manual",
            },
        ),
        (
            "continue until blocked",
            {
                "goal": "continue_until_blocked",
                "allow_draft_generation": True,
                "allow_review_gate_crossing": False,
                "allow_browser_launch": False,
                "execution_mode": "manual",
            },
        ),
        (
            "continue until the next review gate",
            {
                "goal": "continue_to_next_gate",
                "allow_draft_generation": True,
                "allow_review_gate_crossing": False,
                "allow_browser_launch": False,
                "execution_mode": "manual",
            },
        ),
    ],
)
def test_llm_workflow_classifier_contract_examples(
    monkeypatch,
    prompt: str,
    expected: dict[str, object],
) -> None:
    def fake_parse_structured_response(**kwargs):
        prompt_text = kwargs["input"][1]["content"]
        assert prompt in prompt_text
        return WorkflowIntent.model_validate(expected)

    monkeypatch.setattr(
        "src.llm_client.parse_structured_response",
        fake_parse_structured_response,
    )

    intent = classify_karen_workflow_intent_with_llm(
        context=_minimal_karen_context(),
        user_message=prompt,
    )

    assert intent.goal == expected["goal"]
    assert intent.execution_mode == expected["execution_mode"]
    assert intent.allow_review_gate_crossing is bool(
        expected.get("allow_review_gate_crossing", False)
    )
    assert intent.allow_browser_launch is bool(expected.get("allow_browser_launch", False))


def _minimal_karen_context():
    from src.agents.karen.state import KarenContext

    return KarenContext(
        session_id="session-1",
        current_page="Jobs",
        selected_job_id="job-1",
        pending_gate=None,
        next_allowed_actions=["discover_requirements"],
    )


@pytest.mark.parametrize(
    ("state", "intent", "expected_action", "expected_status"),
    [
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                next_allowed_actions=["discover_requirements"],
            ),
            workflow_intent(goal="continue_to_next_gate"),
            "discover_requirements",
            "action",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_status="discovered",
                requirements_review_status="draft",
                requirements_job_preserving=True,
                pending_gate="requirements_review",
            ),
            workflow_intent(goal="continue_to_next_gate", allow_review_gate_crossing=False),
            None,
            "waiting_for_review",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_status="discovered",
                requirements_review_status="draft",
                requirements_job_preserving=True,
                pending_gate="requirements_review",
            ),
            workflow_intent(
                goal="continue_until_blocked",
                allow_review_gate_crossing=True,
            ),
            "review_requirements",
            "action",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_review_status="reviewed",
                package_exists=True,
                package_status="draft",
                pending_gate="package_review",
            ),
            workflow_intent(goal="continue_to_next_gate", allow_review_gate_crossing=False),
            None,
            "waiting_for_review",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_review_status="reviewed",
                package_exists=True,
                package_status="draft",
                pending_gate="package_review",
            ),
            workflow_intent(
                goal="continue_until_blocked",
                allow_review_gate_crossing=True,
            ),
            "review_application_package",
            "action",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_review_status="reviewed",
                package_exists=True,
                package_status="approved",
                fill_plan_exists=True,
                fill_plan_review_status="draft",
                current_blockers=["Save reviewed values for all fields needing answers."],
                pending_gate="fill_plan_review",
                next_allowed_actions=["review_fill_plan", "generate_fill_plan"],
                route_hint="Jobs",
            ),
            workflow_intent(
                goal="continue_until_blocked",
                allow_review_gate_crossing=True,
            ),
            "review_fill_plan",
            "action",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_review_status="reviewed",
                package_exists=True,
                package_status="approved",
                fill_plan_exists=True,
                fill_plan_review_status="reviewed",
                pending_gate="browser_use_launch",
            ),
            workflow_intent(
                goal="launch_browser_application",
                execution_mode="browser_use",
                allow_browser_launch=True,
            ),
            "launch_browser_use",
            "action",
        ),
        (
            CurrentWorkflowState(
                selected_job_id="job-1",
                job_exists=True,
                requirements_exists=True,
                requirements_review_status="reviewed",
                package_exists=True,
                package_status="approved",
                fill_plan_exists=True,
                fill_plan_review_status="reviewed",
                pending_gate="browser_use_launch",
            ),
            workflow_intent(goal="apply_without_browser_use", execution_mode="manual"),
            None,
            "done",
        ),
    ],
)
def test_workflow_planner_next_actions(
    state: CurrentWorkflowState,
    intent: WorkflowIntent,
    expected_action: str | None,
    expected_status: str,
) -> None:
    decision = planner_next_action(state, intent)

    assert decision.status == expected_status
    assert decision.action_name == expected_action


def test_workflow_planner_waits_at_blocked_fill_plan_gate_without_review_permission() -> None:
    state = CurrentWorkflowState(
        selected_job_id="job-1",
        job_exists=True,
        requirements_exists=True,
        requirements_review_status="reviewed",
        package_exists=True,
        package_status="approved",
        fill_plan_exists=True,
        fill_plan_review_status="draft",
        current_blockers=["Save reviewed values for all previously blocked fields."],
        pending_gate="fill_plan_review",
        next_allowed_actions=["review_fill_plan", "generate_fill_plan"],
        route_hint="Jobs",
    )

    decision = planner_next_action(
        state,
        workflow_intent(
            goal="continue_until_blocked",
            allow_review_gate_crossing=False,
        ),
    )

    assert decision.status == "waiting_for_review"
    assert decision.action_name is None


def test_karen_generates_package_by_calling_shared_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    calls: list[tuple[str, str]] = []

    def fake_generate_package(base_dir: Path | str, job_id: str):
        calls.append(("generate_reviewable_application_package", job_id))
        package = make_package(job)
        json_path, markdown_path = save_application_package(base_dir, package, job)
        return package, json_path, markdown_path

    monkeypatch.setattr(
        job_services,
        "generate_reviewable_application_package",
        fake_generate_package,
    )

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="generate application data",
        session_id="karen-generate-package",
        intent_classifier=static_workflow_intent(
            workflow_intent(goal="generate_application_data")
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "waiting_for_review"
    assert calls == [("generate_reviewable_application_package", job.id)]
    package = load_application_package(tmp_path, job.id)
    assert package is not None
    assert package.status == "draft"
    events = load_agent_events(tmp_path, "karen-generate-package")
    assert events[-1].action == "generate_application_package"


def test_karen_does_not_cross_package_review_without_explicit_permission(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job), job)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="continue",
        session_id="karen-no-review-permission",
        intent_classifier=static_workflow_intent(
            workflow_intent(goal="continue_until_blocked", allow_review_gate_crossing=False)
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "waiting_for_review"
    assert result.tool_result.event_details["pending_gate"] == "package_review"
    package = load_application_package(tmp_path, job.id)
    assert package is not None
    assert package.status == "draft"
    assert load_agent_events(tmp_path, "karen-no-review-permission") == []


def test_karen_crosses_package_review_only_with_explicit_permission(
    tmp_path: Path,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job), job)

    result = process_karen_chat_turn(
        tmp_path,
        current_page="Jobs",
        selected_job_id=job.id,
        user_message="approve the package because I reviewed it",
        session_id="karen-review-permission",
        intent_classifier=static_workflow_intent(
            workflow_intent(
                goal="mark_current_gate_reviewed",
                allow_review_gate_crossing=True,
            )
        ),
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "done"
    package = load_application_package(tmp_path, job.id)
    assert package is not None
    assert package.status == "approved"
    events = load_agent_events(tmp_path, "karen-review-permission")
    assert [event.action for event in events] == ["review_application_package"]


def test_karen_blocks_missing_candidate_gender_before_package_generation(
    tmp_path: Path,
) -> None:
    profile, job = setup_profile_and_job(tmp_path)
    profile.candidate_profile.cv_extracted.identity.gender = None
    save_candidate_profile(tmp_path, profile)
    save_reviewed_requirements(tmp_path, job)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-missing-gender",
        selected_job_id=job.id,
        intent=workflow_intent(goal="generate_application_data"),
    )

    assert result.status == "blocked"
    assert result.route_hint == "Candidate Profile"
    assert any("Gender" in blocker for blocker in result.blockers)
    assert load_application_package(tmp_path, job.id) is None


def test_karen_blocks_fill_plan_answers_and_routes_to_jobs(tmp_path: Path) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            needs_answer_fields=[
                ApplicationFillNeedsAnswerField(
                    label="Earliest start date",
                    reason="Requires a reviewed answer.",
                    required=True,
                )
            ],
        ),
    )

    state = load_current_workflow_state(tmp_path, job.id)
    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-fill-plan-blocked",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="continue_until_blocked",
            allow_review_gate_crossing=True,
        ),
    )

    assert state.pending_gate == "fill_plan_review"
    assert state.next_allowed_actions[0] == "review_fill_plan"
    assert result.status == "needs_input"
    assert result.route_hint == "Jobs"
    assert result.executed_actions == ["review_fill_plan"]
    assert "Provide values for required fields" in result.message
    fill_plan = load_application_fill_plan(tmp_path, job.id)
    assert fill_plan is not None
    assert fill_plan.review_status == "draft"


@pytest.mark.parametrize(
    ("fill_plan", "expected_reason"),
    [
        (
            ApplicationFillPlan(
                job_id="placeholder",
                apply_url="https://example.com/apply/automation-engineer",
                review_status="draft",
                upload_files=[
                    ApplicationFillUploadFile(
                        label="CV",
                        file_path="",
                        document_type="cv",
                        required=True,
                    )
                ],
            ),
            "required uploads",
        ),
        (
            ApplicationFillPlan(
                job_id="placeholder",
                apply_url="https://example.com/apply/automation-engineer",
                review_status="draft",
                source_metadata={
                    "candidate_documents": {"cv": {"file_path": "/tmp/reviewed-cv.pdf"}}
                },
                upload_files=[
                    ApplicationFillUploadFile(
                        label="CV",
                        file_path="/tmp/unreviewed-cv.pdf",
                        document_type="cv",
                        required=True,
                    )
                ],
            ),
            "reviewed source file",
        ),
    ],
)
def test_karen_blocks_fill_plan_human_input_boundaries(
    tmp_path: Path,
    fill_plan: ApplicationFillPlan,
    expected_reason: str,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    fill_plan = fill_plan.model_copy(
        update={"job_id": job.id, "apply_url": job.apply_url}
    )
    save_application_fill_plan(tmp_path, fill_plan)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-fill-plan-human-input",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="continue_until_blocked",
            allow_review_gate_crossing=True,
        ),
    )

    assert result.status == "needs_input"
    assert result.route_hint == "Jobs"
    assert result.executed_actions == ["review_fill_plan"]
    assert any(expected_reason in blocker for blocker in result.blockers)
    saved = load_application_fill_plan(tmp_path, job.id)
    assert saved is not None
    assert saved.review_status == "draft"


def test_karen_reports_backend_fill_plan_review_failure_after_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            blocked_fields=[
                ApplicationFillBlockedField(
                    label="Voluntary disclosure",
                    reason="Requires a user decision.",
                )
            ],
        ),
    )
    calls: list[str] = []

    def fail_review_fill_plan(base_dir, job_id, **kwargs):
        calls.append(job_id)
        raise job_services.JobWorkflowServiceError(
            "Save reviewed values for all previously blocked fields."
        )

    monkeypatch.setattr(job_services, "review_fill_plan", fail_review_fill_plan)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-fill-plan-review-backend-blocker",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="continue_until_blocked",
            allow_review_gate_crossing=True,
        ),
    )

    assert calls == [job.id]
    assert result.executed_actions == ["review_fill_plan"]
    assert result.status == "needs_input"
    assert result.route_hint == "Jobs"
    assert "previously blocked fields" in result.message


def test_karen_does_not_attempt_fill_plan_review_without_permission(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="draft",
            blocked_fields=[
                ApplicationFillBlockedField(
                    label="Voluntary disclosure",
                    reason="Requires a user decision.",
                )
            ],
        ),
    )

    def fail_review_fill_plan(*_args, **_kwargs):
        raise AssertionError("Karen should not review a fill plan without permission")

    monkeypatch.setattr(job_services, "review_fill_plan", fail_review_fill_plan)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-fill-plan-no-review-permission",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="continue_until_blocked",
            allow_review_gate_crossing=False,
        ),
    )

    assert result.status == "waiting_for_review"
    assert result.executed_actions == []
    assert result.pending_gate == "fill_plan_review"


def test_karen_manual_mode_does_not_launch_browser_use(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_reviewed_fill_plan(tmp_path, profile, job)

    def fail_launch(*_args, **_kwargs):
        raise AssertionError("Browser Use should not launch in manual mode")

    monkeypatch.setattr(job_services, "launch_apply_assistance", fail_launch)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-manual",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="apply_without_browser_use",
            execution_mode="manual",
            allow_browser_launch=False,
        ),
    )

    assert result.status == "done"
    assert result.executed_actions == []
    assert "manual application" in result.message


def test_karen_launches_browser_use_by_calling_shared_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile, job = setup_profile_and_job(tmp_path)
    save_reviewed_requirements(tmp_path, job)
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_reviewed_fill_plan(tmp_path, profile, job)
    calls: list[str] = []

    def fake_launch(base_dir, job_id, **kwargs):
        calls.append(job_id)
        return SimpleNamespace(
            url="https://example.com/apply/automation-engineer",
            pid=123,
            log_path=Path(base_dir) / "browser.log",
        )

    monkeypatch.setattr(job_services, "launch_apply_assistance", fake_launch)

    result = run_karen_workflow_goal(
        tmp_path,
        session_id="karen-browser",
        selected_job_id=job.id,
        intent=workflow_intent(
            goal="launch_browser_application",
            execution_mode="browser_use",
            allow_browser_launch=True,
        ),
    )

    assert result.status == "done"
    assert result.executed_actions == ["launch_browser_use"]
    assert calls == [job.id]
    assert "Browser Use" in result.message
