"""LangGraph workflow controller for human-gated job application assistance."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict

from src.agent_chat import get_or_create_agent_session, log_agent_event
from src.app_workflow import (
    get_application_package_blockers,
    load_application_page_snapshot,
    load_application_requirements,
    load_candidate_profile,
    load_experience_units,
    load_jobs_index,
    load_normalized_job,
    mark_requirements_reviewed,
)
from src.application_fill_plan import (
    generate_application_fill_plan,
    get_application_fill_plan_freshness_blockers,
    get_application_fill_plan_review_blockers,
    load_application_fill_plan,
    mark_application_fill_plan_reviewed,
    save_application_fill_plan,
)
from src.application_package import (
    generate_application_package,
    reject_application_package,
    save_application_package,
    update_tracker_for_application_package,
)
from src.application_requirements import (
    RequirementsDiscoveryState,
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.browser_use_launcher import open_apply_url_with_browser_use_fill_plan
from src.candidate_profile import validate_candidate_profile
from src.match_analysis import (
    analyze_and_save_match,
    load_match_analysis,
    match_analysis_is_fresh,
    review_match_analysis,
)
from src.paths import (
    RUNTIME_DATA_DIR,
    runtime_application_fill_plan_path,
    runtime_application_package_path,
    runtime_application_requirements_path,
    runtime_jobs_index_path,
    runtime_match_analysis_path,
    runtime_tracker_path,
)
from src.schemas import (
    AgentGate,
    AgentWorkflowEvent,
    AgentWorkflowState,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    MatchAnalysis,
    TrackerRecord,
)
from src.storage import load_model, save_model

AgentAction = str


class RequirementsDiscoverer(Protocol):
    """Callable contract for requirements discovery from a reviewed job."""

    def __call__(self, job: JobListing) -> RequirementsDiscoveryState:
        """Return discovered requirements state for a job."""
        ...


class PackageGenerator(Protocol):
    """Callable contract for generating an application package."""

    def __call__(
        self,
        candidate_profile: CandidateProfile,
        experience_units: list[ExperienceUnit],
        job: JobListing,
        requirements: ApplicationRequirements | None,
    ) -> ApplicationPackage:
        """Return a draft application package."""
        ...


class FillPlanGenerator(Protocol):
    """Callable contract for generating an application fill plan."""

    def __call__(
        self,
        candidate_profile: CandidateProfile,
        requirements: ApplicationRequirements,
        package: ApplicationPackage,
        page_snapshot: ApplicationPageSnapshot | None,
    ) -> ApplicationFillPlan:
        """Return a draft fill plan."""
        ...


class BrowserUseLauncher(Protocol):
    """Callable contract for explicit Browser Use launch approval."""

    def __call__(
        self,
        url: str,
        *,
        fill_plan: ApplicationFillPlan,
        log_dir: Path,
        candidate_profile: CandidateProfile,
        requirements: ApplicationRequirements,
        package: ApplicationPackage,
    ) -> object:
        """Launch Browser Use with a reviewed fill plan."""
        ...


@dataclass(frozen=True)
class AgentWorkflowDependencies:
    """Injectable workflow steps used by tests and the runtime API controller."""

    requirements_discoverer: RequirementsDiscoverer = run_requirements_discovery_graph
    package_generator: PackageGenerator = generate_application_package
    fill_plan_generator: FillPlanGenerator = field(
        default_factory=lambda: _default_fill_plan_generator
    )
    browser_launcher: BrowserUseLauncher = open_apply_url_with_browser_use_fill_plan


@dataclass(frozen=True)
class ActionResult:
    """Result metadata for one workflow action."""

    action: str
    result: str
    gate: AgentGate | None = None
    artifact_paths: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class AgentGraphState(TypedDict, total=False):
    """State passed through the agent workflow graph."""

    base_dir: Path
    session_id: str
    selected_job_id: str | None
    action: str
    dependencies: AgentWorkflowDependencies
    last_user_intent: str | None
    candidate_profile: CandidateProfile
    tracker_records: list[TrackerRecord]
    job: JobListing | None
    experience_units: list[ExperienceUnit]
    analysis: MatchAnalysis | None
    requirements: ApplicationRequirements | None
    page_snapshot: ApplicationPageSnapshot | None
    package: ApplicationPackage | None
    fill_plan: ApplicationFillPlan | None
    events: list[ActionResult]
    errors: list[str]
    workflow_state: AgentWorkflowState


def run_agent_workflow(
    base_dir: Path | str,
    *,
    session_id: str | None = None,
    selected_job_id: str | None = None,
    action: str = "status",
    last_user_intent: str | None = None,
    dependencies: AgentWorkflowDependencies | None = None,
) -> AgentWorkflowState:
    """Run the agent workflow controller until it reaches a human gate."""

    base_path = Path(base_dir)
    session = get_or_create_agent_session(
        base_path,
        session_id,
        selected_job_id=selected_job_id,
    )
    active_job_id = selected_job_id or session.selected_job_id
    initial_state: AgentGraphState = {
        "base_dir": base_path,
        "session_id": session.session_id,
        "selected_job_id": active_job_id,
        "action": action,
        "dependencies": dependencies or AgentWorkflowDependencies(),
        "last_user_intent": last_user_intent,
        "events": [],
        "errors": [],
    }
    graph = build_agent_workflow_graph()
    result = graph.invoke(initial_state)
    return result["workflow_state"]


def build_agent_workflow_graph():
    """Build the LangGraph workflow controller or a sequential fallback."""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialAgentWorkflowGraph()

    graph = StateGraph(AgentGraphState)
    graph.add_node("load_context", _load_context_node)
    graph.add_node("execute_action", _execute_action_node)
    graph.add_node("reload_context", _load_context_node)
    graph.add_node("refresh_state", _refresh_state_node)
    graph.add_node("log_events", _log_events_node)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "execute_action")
    graph.add_edge("execute_action", "reload_context")
    graph.add_edge("reload_context", "refresh_state")
    graph.add_edge("refresh_state", "log_events")
    graph.add_edge("log_events", END)
    return graph.compile()


def get_apply_assistance_blockers(
    job: JobListing,
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
    *,
    candidate_profile: CandidateProfile | None = None,
) -> list[str]:
    """Return blockers that prevent explicit Browser Use launch."""

    blockers: list[str] = []
    if job.apply_url is None:
        blockers.append("Resolve and save a valid apply URL.")

    if requirements is None:
        blockers.append("Discover application requirements for this apply URL.")
    elif requirements.status != "discovered" or not requirements.job_preserving:
        blockers.append("Resolve reviewed application requirements before applying.")
    elif requirements.review_status != "reviewed":
        blockers.append("Review the discovered application requirements.")

    if package is None:
        blockers.append("Generate the application package before applying.")
    elif package.status == "rejected":
        blockers.append("Regenerate or manually edit the rejected application package.")
    elif package.status != "approved":
        blockers.append("Save the application package review before applying.")

    if fill_plan is None:
        blockers.append("Generate the application fill plan before applying.")
    else:
        review_blockers = get_application_fill_plan_review_blockers(fill_plan)
        if review_blockers:
            blockers.extend(review_blockers)
        elif fill_plan.review_status != "reviewed":
            blockers.append("Review the application fill plan before applying.")
        elif (
            candidate_profile is not None
            and requirements is not None
            and package is not None
        ):
            blockers.extend(
                get_application_fill_plan_freshness_blockers(
                    fill_plan,
                    candidate_profile,
                    requirements,
                    package,
                )
            )

    return blockers


def approve_application_package(package: ApplicationPackage) -> ApplicationPackage:
    """Return a package and all artifacts marked as approved."""

    reviewed = package.model_copy(deep=True)
    reviewed.status = "approved"
    for artifact in reviewed.artifacts:
        artifact.status = "approved"
    return reviewed


class _SequentialAgentWorkflowGraph:
    def invoke(self, state: AgentGraphState) -> AgentGraphState:
        next_state = dict(state)
        next_state.update(_load_context_node(next_state))
        next_state.update(_execute_action_node(next_state))
        next_state.update(_load_context_node(next_state))
        next_state.update(_refresh_state_node(next_state))
        next_state.update(_log_events_node(next_state))
        return next_state


def _default_fill_plan_generator(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements,
    package: ApplicationPackage,
    page_snapshot: ApplicationPageSnapshot | None,
) -> ApplicationFillPlan:
    return generate_application_fill_plan(
        candidate_profile,
        requirements,
        package,
        page_snapshot=page_snapshot,
    )


def _load_context_node(state: AgentGraphState) -> AgentGraphState:
    base_dir = state["base_dir"]
    selected_job_id = state.get("selected_job_id")
    job = load_normalized_job(base_dir, selected_job_id) if selected_job_id else None
    return {
        "candidate_profile": load_candidate_profile(base_dir),
        "tracker_records": load_jobs_index(base_dir),
        "job": job,
        "experience_units": load_experience_units(base_dir),
        "analysis": load_match_analysis(base_dir, selected_job_id) if selected_job_id else None,
        "requirements": (
            load_application_requirements(base_dir, selected_job_id)
            if selected_job_id
            else None
        ),
        "page_snapshot": (
            load_application_page_snapshot(base_dir, selected_job_id)
            if selected_job_id
            else None
        ),
        "package": _load_application_package(base_dir, selected_job_id),
        "fill_plan": _load_application_fill_plan(base_dir, selected_job_id),
    }


def _execute_action_node(state: AgentGraphState) -> AgentGraphState:
    action = state.get("action", "status")
    if action in {"status", "refresh_state", ""}:
        return {}

    events = list(state.get("events", []))
    errors = list(state.get("errors", []))
    try:
        if action == "continue":
            events.extend(_execute_continue_until_gate(state))
        else:
            events.append(_execute_single_action(state, action))
    except (RuntimeError, ValueError) as exc:
        errors.append(str(exc))
        events.append(
            ActionResult(
                action=action,
                result="error",
                details={"error": str(exc)},
            )
        )
    return {"events": events, "errors": errors}


def _refresh_state_node(state: AgentGraphState) -> AgentGraphState:
    return {"workflow_state": _build_workflow_state(state)}


def _log_events_node(state: AgentGraphState) -> AgentGraphState:
    base_dir = state["base_dir"]
    session_id = state["session_id"]
    job_id = state.get("selected_job_id")
    for event in state.get("events", []):
        log_agent_event(
            base_dir,
            AgentWorkflowEvent(
                session_id=session_id,
                job_id=job_id,
                action=event.action,
                result=event.result,
                gate=event.gate,
                artifact_paths=event.artifact_paths,
                details=event.details,
            ),
        )
    return {}


def _execute_continue_until_gate(state: AgentGraphState) -> list[ActionResult]:
    events: list[ActionResult] = []
    current_state = dict(state)
    for _ in range(8):
        snapshot = _build_workflow_state(current_state)
        if snapshot.pending_gate and snapshot.pending_gate != "browser_use_launch":
            break
        if snapshot.blockers and not _has_regeneration_action(snapshot):
            break
        next_action = _next_auto_action(current_state, snapshot)
        if next_action is None:
            break
        event = _execute_single_action(current_state, next_action)
        events.append(event)
        current_state.update(_load_context_node(current_state))
        if event.gate:
            break
    return events


def _execute_single_action(state: AgentGraphState, action: str) -> ActionResult:
    if action == "analyze_match":
        return _analyze_match_action(state)
    if action == "review_match":
        return _review_match_action(state, accepted=True)
    if action == "reject_match":
        return _review_match_action(state, accepted=False)
    if action == "discover_requirements":
        return _discover_requirements_action(state)
    if action == "review_requirements":
        return _review_requirements_action(state)
    if action == "generate_package":
        return _generate_package_action(state)
    if action == "approve_package":
        return _approve_package_action(state)
    if action == "reject_package":
        return _reject_package_action(state)
    if action == "generate_fill_plan":
        return _generate_fill_plan_action(state)
    if action == "review_fill_plan":
        return _review_fill_plan_action(state)
    if action == "prepare_apply_assistance":
        return _prepare_apply_assistance_action(state)
    if action == "launch_browser_use":
        return _launch_browser_use_action(state)
    raise ValueError(f"Unsupported agent workflow action: {action}")


def _analyze_match_action(state: AgentGraphState) -> ActionResult:
    candidate_profile = state["candidate_profile"]
    job = _require_job(state)
    experience_units = state.get("experience_units", [])
    profile_errors = validate_candidate_profile(candidate_profile)
    if profile_errors:
        raise ValueError("Complete the candidate profile: " + ", ".join(profile_errors))
    existing = state.get("analysis")
    if existing is not None and match_analysis_is_fresh(
        existing,
        candidate_profile,
        job,
        experience_units,
    ):
        return ActionResult(
            action="analyze_match",
            result="skipped_fresh_match_analysis",
            gate="match_review" if existing.review_status == "draft" else None,
            artifact_paths=[str(runtime_match_analysis_path(state["base_dir"], job.id))],
            details={"match_score": existing.match_score},
        )
    analysis = analyze_and_save_match(
        state["base_dir"],
        candidate_profile,
        job,
        experience_units,
    )
    return ActionResult(
        action="analyze_match",
        result="saved_match_analysis",
        gate="match_review" if analysis.review_status == "draft" else None,
        artifact_paths=[str(runtime_match_analysis_path(state["base_dir"], job.id))],
        details={"match_score": analysis.match_score},
    )


def _review_match_action(state: AgentGraphState, *, accepted: bool) -> ActionResult:
    analysis = _require_analysis(state)
    reviewed = review_match_analysis(state["base_dir"], analysis, accepted=accepted)
    result = "reviewed_match_analysis" if accepted else "rejected_match_analysis"
    return ActionResult(
        action="review_match" if accepted else "reject_match",
        result=result,
        artifact_paths=[str(runtime_match_analysis_path(state["base_dir"], analysis.job_id))],
        details={"review_status": reviewed.review_status, "match_score": reviewed.match_score},
    )


def _discover_requirements_action(state: AgentGraphState) -> ActionResult:
    job = _require_job(state)
    if job.apply_url is None:
        raise ValueError("Apply URL is required before discovering application requirements.")
    existing = state.get("requirements")
    if existing is not None:
        return ActionResult(
            action="discover_requirements",
            result="skipped_existing_requirements",
            gate="requirements_review" if existing.review_status != "reviewed" else None,
            artifact_paths=[
                str(runtime_application_requirements_path(state["base_dir"], job.id)),
            ],
        )

    discovery_state = state["dependencies"].requirements_discoverer(job)
    snapshot = discovery_state["snapshot"]
    requirements = discovery_state["requirements"]
    snapshot_path = save_application_page_snapshot(state["base_dir"], job.id, snapshot)
    requirements_path = save_application_requirements(state["base_dir"], requirements)
    return ActionResult(
        action="discover_requirements",
        result="saved_application_requirements",
        gate="requirements_review",
        artifact_paths=[str(snapshot_path), str(requirements_path)],
        details={"status": requirements.status, "job_preserving": requirements.job_preserving},
    )


def _review_requirements_action(state: AgentGraphState) -> ActionResult:
    requirements = _require_requirements(state)
    if requirements.status != "discovered" or not requirements.job_preserving:
        raise ValueError("Application requirements must preserve the selected job before review.")
    reviewed = mark_requirements_reviewed(requirements)
    path = save_application_requirements(state["base_dir"], reviewed)
    return ActionResult(
        action="review_requirements",
        result="reviewed_application_requirements",
        artifact_paths=[str(path)],
    )


def _generate_package_action(state: AgentGraphState) -> ActionResult:
    candidate_profile = state["candidate_profile"]
    job = _require_job(state)
    requirements = state.get("requirements")
    existing = state.get("package")
    if existing is not None:
        return ActionResult(
            action="generate_package",
            result="skipped_existing_package",
            gate="package_review" if existing.status != "approved" else None,
            artifact_paths=[str(runtime_application_package_path(state["base_dir"], job.id))],
        )

    blockers = get_application_package_blockers(candidate_profile, job, requirements)
    if blockers:
        raise ValueError(" ".join(blockers))

    package = state["dependencies"].package_generator(
        candidate_profile,
        state.get("experience_units", []),
        job,
        requirements,
    )
    json_path, markdown_path = save_application_package(state["base_dir"], package, job)
    update_tracker_for_application_package(state["base_dir"], job.id, json_path)
    return ActionResult(
        action="generate_package",
        result="saved_application_package",
        gate="package_review",
        artifact_paths=[str(json_path), str(markdown_path)],
        details={"status": package.status},
    )


def _approve_package_action(state: AgentGraphState) -> ActionResult:
    job = _require_job(state)
    package = _require_package(state)
    reviewed = approve_application_package(package)
    json_path, markdown_path = save_application_package(state["base_dir"], reviewed, job)
    return ActionResult(
        action="approve_package",
        result="approved_application_package",
        artifact_paths=[str(json_path), str(markdown_path)],
        details={"status": reviewed.status},
    )


def _reject_package_action(state: AgentGraphState) -> ActionResult:
    job = _require_job(state)
    package = _require_package(state)
    rejected = reject_application_package(package, "Rejected from agent workflow review.")
    json_path, markdown_path = save_application_package(state["base_dir"], rejected, job)
    return ActionResult(
        action="reject_package",
        result="rejected_application_package",
        gate="package_review",
        artifact_paths=[str(json_path), str(markdown_path)],
        details={"status": rejected.status},
    )


def _generate_fill_plan_action(state: AgentGraphState) -> ActionResult:
    existing = state.get("fill_plan")
    if existing is not None and existing.review_status == "draft":
        return ActionResult(
            action="generate_fill_plan",
            result="skipped_existing_fill_plan",
            gate="fill_plan_review",
            artifact_paths=[
                str(runtime_application_fill_plan_path(state["base_dir"], existing.job_id)),
            ],
        )

    candidate_profile = state["candidate_profile"]
    requirements = _require_requirements(state)
    package = _require_package(state)
    if package.status != "approved":
        raise ValueError("Approve the application package before generating a fill plan.")
    if requirements.review_status != "reviewed":
        raise ValueError("Review application requirements before generating a fill plan.")
    if existing is not None:
        freshness_blockers = get_application_fill_plan_freshness_blockers(
            existing,
            candidate_profile,
            requirements,
            package,
        )
        if existing.review_status == "reviewed" and not freshness_blockers:
            return ActionResult(
                action="generate_fill_plan",
                result="skipped_fresh_fill_plan",
                artifact_paths=[
                    str(runtime_application_fill_plan_path(state["base_dir"], existing.job_id)),
                ],
            )

    fill_plan = state["dependencies"].fill_plan_generator(
        candidate_profile,
        requirements,
        package,
        state.get("page_snapshot"),
    )
    path = save_application_fill_plan(state["base_dir"], fill_plan)
    return ActionResult(
        action="generate_fill_plan",
        result="saved_application_fill_plan",
        gate="fill_plan_review",
        artifact_paths=[str(path)],
    )


def _review_fill_plan_action(state: AgentGraphState) -> ActionResult:
    fill_plan = _require_fill_plan(state)
    reviewed = mark_application_fill_plan_reviewed(fill_plan)
    path = save_application_fill_plan(state["base_dir"], reviewed)
    _update_tracker_status(state["base_dir"], reviewed.job_id, "ready_to_apply")
    return ActionResult(
        action="review_fill_plan",
        result="reviewed_application_fill_plan",
        artifact_paths=[str(path)],
    )


def _prepare_apply_assistance_action(state: AgentGraphState) -> ActionResult:
    job = _require_job(state)
    blockers = get_apply_assistance_blockers(
        job,
        state.get("requirements"),
        state.get("package"),
        state.get("fill_plan"),
        candidate_profile=state.get("candidate_profile"),
    )
    if blockers:
        raise ValueError(" ".join(blockers))
    return ActionResult(
        action="prepare_apply_assistance",
        result="ready_for_browser_use_launch",
        gate="browser_use_launch",
    )


def _launch_browser_use_action(state: AgentGraphState) -> ActionResult:
    job = _require_job(state)
    requirements = _require_requirements(state)
    package = _require_package(state)
    fill_plan = _require_fill_plan(state)
    blockers = get_apply_assistance_blockers(
        job,
        requirements,
        package,
        fill_plan,
        candidate_profile=state["candidate_profile"],
    )
    if blockers:
        raise ValueError(" ".join(blockers))
    result = state["dependencies"].browser_launcher(
        str(job.apply_url),
        fill_plan=fill_plan,
        log_dir=Path(state["base_dir"]) / RUNTIME_DATA_DIR / "browser_use",
        candidate_profile=state["candidate_profile"],
        requirements=requirements,
        package=package,
    )
    return ActionResult(
        action="launch_browser_use",
        result="browser_use_started",
        gate="browser_use_launch",
        details={"launcher_result": str(result)},
    )


def _build_workflow_state(state: AgentGraphState) -> AgentWorkflowState:
    selected_job_id = state.get("selected_job_id")
    artifacts = {
        "normalized_job": state.get("job") is not None,
        "application_requirements": state.get("requirements") is not None,
        "application_page_snapshot": state.get("page_snapshot") is not None,
        "application_package": state.get("package") is not None,
        "application_fill_plan": state.get("fill_plan") is not None,
    }
    blockers = _current_blockers(state)
    pending_gate = _pending_gate(state)
    return AgentWorkflowState(
        session_id=state["session_id"],
        selected_job_id=selected_job_id,
        artifacts_present=artifacts,
        blockers=blockers,
        next_allowed_actions=_next_allowed_actions(state, blockers, pending_gate),
        pending_gate=pending_gate,
        errors=list(state.get("errors", [])),
        last_user_intent=state.get("last_user_intent"),
    )


def _current_blockers(state: AgentGraphState) -> list[str]:
    blockers: list[str] = []
    selected_job_id = state.get("selected_job_id")
    job = state.get("job")
    candidate_profile = state.get("candidate_profile")
    if not selected_job_id:
        blockers.append("Select a job before running the agent workflow.")
        return blockers
    if job is None:
        blockers.append("Reviewed normalized job data is missing.")
        return blockers
    if candidate_profile is not None:
        profile_errors = validate_candidate_profile(candidate_profile)
        if profile_errors:
            blockers.append("Complete the candidate profile: " + ", ".join(profile_errors))

    if job.apply_url is None:
        blockers.append("Apply URL is required before requirements discovery.")

    requirements = state.get("requirements")
    if requirements is not None and requirements.status == "blocked":
        blockers.append("Application requirements are blocked for this apply URL.")

    package = state.get("package")
    fill_plan = state.get("fill_plan")
    if (
        package is not None
        and package.status == "approved"
        and fill_plan is not None
        and fill_plan.review_status == "reviewed"
        and candidate_profile is not None
        and requirements is not None
    ):
        blockers.extend(
            get_application_fill_plan_freshness_blockers(
                fill_plan,
                candidate_profile,
                requirements,
                package,
            )
        )
    return blockers


def _pending_gate(state: AgentGraphState) -> AgentGate | None:
    if not state.get("selected_job_id"):
        return "select_job"
    if state.get("job") is None:
        return None

    requirements = state.get("requirements")
    if requirements is not None and requirements.review_status != "reviewed":
        return "requirements_review"
    if requirements is None:
        return None

    package = state.get("package")
    if package is not None and package.status != "approved":
        return "package_review"
    if package is None:
        return None

    fill_plan = state.get("fill_plan")
    if fill_plan is not None and fill_plan.review_status != "reviewed":
        return "fill_plan_review"
    if fill_plan is None:
        return None
    return "browser_use_launch"


def _next_allowed_actions(
    state: AgentGraphState,
    blockers: list[str],
    pending_gate: AgentGate | None,
) -> list[str]:
    if state.get("job") is None:
        return []
    if blockers and not _only_regeneration_blockers(blockers):
        return []
    if pending_gate == "requirements_review":
        return ["review_requirements", "discover_requirements"]
    if pending_gate == "package_review":
        return ["approve_package", "reject_package", "generate_package"]
    if pending_gate == "fill_plan_review":
        return ["review_fill_plan", "generate_fill_plan"]
    if pending_gate == "browser_use_launch":
        return ["prepare_apply_assistance", "launch_browser_use"]

    next_auto_action = _next_auto_action(state, _build_minimal_state(state))
    return [next_auto_action] if next_auto_action else []


def _next_auto_action(
    state: AgentGraphState,
    snapshot: AgentWorkflowState,
) -> str | None:
    if snapshot.blockers and not _only_regeneration_blockers(snapshot.blockers):
        return None
    job = state.get("job")
    if job is None:
        return None

    requirements = state.get("requirements")
    if requirements is None:
        return "discover_requirements"
    if requirements.review_status != "reviewed":
        return None

    package = state.get("package")
    if package is None:
        return "generate_package"
    if package.status != "approved":
        return None

    fill_plan = state.get("fill_plan")
    if fill_plan is None:
        return "generate_fill_plan"
    if fill_plan.review_status != "reviewed":
        return None
    return "prepare_apply_assistance"


def _build_minimal_state(state: AgentGraphState) -> AgentWorkflowState:
    return AgentWorkflowState(
        session_id=state["session_id"],
        selected_job_id=state.get("selected_job_id"),
        blockers=_current_blockers(state),
        pending_gate=_pending_gate(state),
    )


def _has_regeneration_action(snapshot: AgentWorkflowState) -> bool:
    return any(
        action in snapshot.next_allowed_actions
        for action in ("generate_fill_plan",)
    )


def _only_regeneration_blockers(blockers: list[str]) -> bool:
    if not blockers:
        return False
    return all(
        "stale" in blocker.casefold() or "changed since review" in blocker.casefold()
        for blocker in blockers
    )


def _analysis_is_stale(state: AgentGraphState) -> bool:
    analysis = state.get("analysis")
    job = state.get("job")
    candidate_profile = state.get("candidate_profile")
    if analysis is None or job is None or candidate_profile is None:
        return False
    return not match_analysis_is_fresh(
        analysis,
        candidate_profile,
        job,
        state.get("experience_units", []),
    )


def _load_application_package(
    base_dir: Path | str,
    job_id: str | None,
) -> ApplicationPackage | None:
    if not job_id:
        return None
    from src.application_package import load_application_package

    return load_application_package(base_dir, job_id)


def _load_application_fill_plan(
    base_dir: Path | str,
    job_id: str | None,
) -> ApplicationFillPlan | None:
    if not job_id:
        return None
    return load_application_fill_plan(base_dir, job_id)


def _require_job(state: AgentGraphState) -> JobListing:
    job = state.get("job")
    if job is None:
        raise ValueError("Reviewed normalized job data is missing.")
    return job


def _require_analysis(state: AgentGraphState) -> MatchAnalysis:
    analysis = state.get("analysis")
    if analysis is None:
        raise ValueError("Run match analysis before reviewing it.")
    return analysis


def _require_requirements(state: AgentGraphState) -> ApplicationRequirements:
    requirements = state.get("requirements")
    if requirements is None:
        raise ValueError("Discover application requirements first.")
    return requirements


def _require_package(state: AgentGraphState) -> ApplicationPackage:
    package = state.get("package")
    if package is None:
        raise ValueError("Generate the application package first.")
    return package


def _require_fill_plan(state: AgentGraphState) -> ApplicationFillPlan:
    fill_plan = state.get("fill_plan")
    if fill_plan is None:
        raise ValueError("Generate the application fill plan first.")
    return fill_plan


def _update_tracker_status(base_dir: Path | str, job_id: str, status: str) -> None:
    jobs_index_path = runtime_jobs_index_path(base_dir)
    tracker_path = runtime_tracker_path(base_dir)
    tracker_records = load_model(jobs_index_path, list[TrackerRecord], default=[])
    for record in tracker_records:
        if record.job_id == job_id:
            record.status = status  # type: ignore[assignment]
            break
    save_model(jobs_index_path, tracker_records)
    save_model(tracker_path, tracker_records)
