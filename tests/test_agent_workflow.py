from __future__ import annotations

from pathlib import Path

from src.agent_chat import load_agent_events
from src.agent_workflow import AgentWorkflowDependencies, run_agent_workflow
from src.app_workflow import save_candidate_profile
from src.application_fill_plan import generate_application_fill_plan, save_application_fill_plan
from src.application_package import save_application_package
from src.application_requirements import (
    RequirementsDiscoveryState,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.job_intake import create_job_listing, persist_job_listing, save_normalized_job
from src.match_analysis import analyze_match, review_match_analysis, save_match_analysis
from src.schemas import (
    ApplicationArtifact,
    ApplicationFillFieldValue,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateProfile,
    JobListing,
)


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


def make_job(*, apply_url: str = "https://example.com/apply/automation-engineer"):
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url=apply_url,
        location="Berlin",
        remote_policy="Hybrid",
        description="Build workflow automation tools.",
        requirements=["Python", "SQL", "Workflow automation"],
    )


def make_requirements(job: JobListing, *, reviewed: bool = False) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        status="discovered",
        review_status="reviewed" if reviewed else "draft",
        job_preserving=True,
    )


def make_package(job: JobListing, *, status: str = "draft") -> ApplicationPackage:
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


def make_fill_plan(job: JobListing, *, reviewed: bool = False) -> ApplicationFillPlan:
    return ApplicationFillPlan(
        job_id=job.id,
        apply_url=str(job.apply_url),
        review_status="reviewed" if reviewed else "draft",
        field_values=[
            ApplicationFillFieldValue(
                label="First name",
                value="Taylor",
                required=True,
            )
        ],
    )


def setup_job(tmp_path: Path, *, apply_url: str = "https://example.com/apply/automation-engineer"):
    profile = make_profile()
    job = make_job(apply_url=apply_url)
    save_candidate_profile(tmp_path, profile)
    persist_job_listing(tmp_path, job)
    return profile, job


def save_reviewed_analysis(tmp_path: Path, profile: CandidateProfile, job: JobListing) -> None:
    analysis = analyze_match(profile, job, [])
    review_match_analysis(tmp_path, analysis, accepted=True)


def fake_requirements_discoverer(job: JobListing) -> RequirementsDiscoveryState:
    snapshot = ApplicationPageSnapshot(
        requested_url=str(job.apply_url),
        final_url=str(job.apply_url),
    )
    requirements = make_requirements(job)
    return {"job": job, "snapshot": snapshot, "requirements": requirements}


def fake_package_generator(
    _profile: CandidateProfile,
    _units: list,
    job: JobListing,
    _requirements: ApplicationRequirements | None,
) -> ApplicationPackage:
    return make_package(job)


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


def workflow_dependencies() -> AgentWorkflowDependencies:
    return AgentWorkflowDependencies(
        requirements_discoverer=fake_requirements_discoverer,
        package_generator=fake_package_generator,
        fill_plan_generator=fake_fill_plan_generator,
        browser_launcher=lambda *_args, **_kwargs: "started",
    )


def test_agent_workflow_runs_happy_path_until_browser_launch_gate(tmp_path: Path) -> None:
    _, job = setup_job(tmp_path)
    deps = workflow_dependencies()

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="continue",
        dependencies=deps,
    )
    assert state.pending_gate == "requirements_review"

    run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="review_requirements",
        dependencies=deps,
    )
    state = run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="continue",
        dependencies=deps,
    )
    assert state.pending_gate == "package_review"

    run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="approve_package",
        dependencies=deps,
    )
    state = run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="continue",
        dependencies=deps,
    )
    assert state.pending_gate == "fill_plan_review"

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-happy",
        selected_job_id=job.id,
        action="review_fill_plan",
        dependencies=deps,
    )
    assert state.pending_gate == "browser_use_launch"
    assert "launch_browser_use" in state.next_allowed_actions


def test_agent_workflow_permissioned_continue_launches_browser_use(
    tmp_path: Path,
) -> None:
    _, job = setup_job(tmp_path)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-permissioned-apply",
        selected_job_id=job.id,
        action="continue_to_apply_assistance",
        dependencies=workflow_dependencies(),
    )

    assert state.pending_gate == "browser_use_launch"
    assert "launch_browser_use" in state.next_allowed_actions
    events = load_agent_events(tmp_path, "agent-permissioned-apply")
    assert [event.action for event in events] == [
        "discover_requirements",
        "review_requirements",
        "generate_package",
        "approve_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
    ]
    assert events[-1].result == "browser_use_started"


def test_agent_workflow_permissioned_continue_approves_needs_review_package(
    tmp_path: Path,
) -> None:
    _, job = setup_job(tmp_path)
    save_application_requirements(tmp_path, make_requirements(job, reviewed=True))
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )
    save_application_package(tmp_path, make_package(job, status="needs_review"), job)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-permissioned-needs-review-package",
        selected_job_id=job.id,
        action="continue_to_apply_assistance",
        dependencies=workflow_dependencies(),
    )

    assert state.pending_gate == "browser_use_launch"
    events = load_agent_events(tmp_path, "agent-permissioned-needs-review-package")
    assert [event.action for event in events] == [
        "approve_package",
        "generate_fill_plan",
        "review_fill_plan",
        "launch_browser_use",
    ]
    assert events[-1].result == "browser_use_started"


def test_agent_workflow_starts_known_job_at_requirements_discovery(tmp_path: Path) -> None:
    _, job = setup_job(tmp_path)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-known-job-start",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert state.pending_gate is None
    assert state.next_allowed_actions == ["discover_requirements"]


def test_agent_workflow_blocks_missing_profile_for_package_generation(tmp_path: Path) -> None:
    job = make_job()
    persist_job_listing(tmp_path, job)
    save_application_requirements(tmp_path, make_requirements(job, reviewed=True))

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-missing-profile",
        selected_job_id=job.id,
        action="generate_package",
        dependencies=workflow_dependencies(),
    )

    assert state.errors
    assert "Complete the candidate profile" in state.errors[0]


def test_agent_workflow_blocks_missing_apply_url_before_requirements(tmp_path: Path) -> None:
    _, job = setup_job(tmp_path, apply_url="")

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-no-apply-url",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert "Apply URL is required before requirements discovery." in state.blockers
    assert state.next_allowed_actions == []


def test_agent_workflow_ignores_historical_rejected_match_in_active_path(tmp_path: Path) -> None:
    profile, job = setup_job(tmp_path)
    analysis = analyze_match(profile, job, [])
    review_match_analysis(tmp_path, analysis, accepted=False)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-reject",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert "Match analysis was rejected by the user." not in state.blockers
    assert state.next_allowed_actions == ["discover_requirements"]


def test_agent_workflow_surfaces_blocked_requirements(tmp_path: Path) -> None:
    _, job = setup_job(tmp_path)
    blocked = make_requirements(job)
    blocked.status = "blocked"
    blocked.job_preserving = False
    save_application_requirements(tmp_path, blocked)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-blocked-reqs",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert "Application requirements are blocked for this apply URL." in state.blockers


def test_agent_workflow_stops_at_unapproved_package(tmp_path: Path) -> None:
    profile, job = setup_job(tmp_path)
    save_application_requirements(tmp_path, make_requirements(job, reviewed=True))
    save_application_package(tmp_path, make_package(job, status="draft"), job)

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-package-review",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert state.pending_gate == "package_review"
    assert "approve_package" in state.next_allowed_actions


def test_agent_workflow_stops_at_unreviewed_fill_plan(tmp_path: Path) -> None:
    profile, job = setup_job(tmp_path)
    requirements = make_requirements(job, reviewed=True)
    save_application_requirements(tmp_path, requirements)
    save_application_page_snapshot(
        tmp_path,
        job.id,
        ApplicationPageSnapshot(requested_url=str(job.apply_url)),
    )
    save_application_package(tmp_path, make_package(job, status="approved"), job)
    save_application_fill_plan(tmp_path, make_fill_plan(job, reviewed=False))

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-fill-review",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert state.pending_gate == "fill_plan_review"
    assert "review_fill_plan" in state.next_allowed_actions


def test_agent_workflow_skips_existing_fresh_match_analysis(tmp_path: Path) -> None:
    profile, job = setup_job(tmp_path)
    save_match_analysis(tmp_path, analyze_match(profile, job, []))

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-idempotent",
        selected_job_id=job.id,
        action="analyze_match",
        dependencies=workflow_dependencies(),
    )

    events = load_agent_events(tmp_path, "agent-idempotent")
    assert state.pending_gate is None
    assert state.next_allowed_actions == ["discover_requirements"]
    assert events[0].result == "skipped_fresh_match_analysis"


def test_agent_workflow_ignores_stale_historical_match_analysis(tmp_path: Path) -> None:
    profile, job = setup_job(tmp_path)
    save_match_analysis(tmp_path, analyze_match(profile, job, []))
    save_normalized_job(
        tmp_path,
        job.model_copy(update={"requirements": [*job.requirements, "Kubernetes"]}),
    )

    state = run_agent_workflow(
        tmp_path,
        session_id="agent-stale-analysis",
        selected_job_id=job.id,
        dependencies=workflow_dependencies(),
    )

    assert "Match analysis is stale and should be regenerated." not in state.blockers
    assert state.next_allowed_actions == ["discover_requirements"]
