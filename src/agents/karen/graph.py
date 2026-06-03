"""LangGraph-compatible chat controller for Karen."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import yaml

from src import llm_client
from src.agent_chat import (
    ACTION_LABELS,
    GATE_LABELS,
    append_agent_chat_message,
    log_agent_event,
)
from src.agents.karen.policy import evaluate_karen_tool_request
from src.agents.karen.state import (
    KarenChatTurnResult,
    KarenContext,
    KarenIntentResponse,
    KarenToolResult,
)
from src.agents.karen.tools import (
    build_karen_context,
    execute_karen_tool,
    get_karen_tool_definition,
)
from src.schemas import AgentChatMessage, AgentWorkflowEvent
from src.services.karen_permission_service import grant_job_session_permission
from src.workflow.workflow_executor import WorkflowRunResult, run_karen_workflow_goal
from src.workflow.workflow_planner import WorkflowIntent

KAREN_PROMPTS_PATH = Path(__file__).with_name("prompts.yaml")
KarenIntentClassifier = Callable[[KarenContext, str], KarenIntentResponse]


class KarenGraphState(TypedDict, total=False):
    """State passed through Karen's chat graph."""

    base_dir: Path
    current_page: str
    selected_job_id: str | None
    session_id: str | None
    user_message: str
    intent_classifier: KarenIntentClassifier | None
    workflow_run_id: str | None
    context: KarenContext
    intent: KarenIntentResponse | None
    tool_result: KarenToolResult | None
    assistant_message: str
    inline_permission_granted: bool


def process_karen_chat_turn(
    base_dir: Path | str,
    *,
    current_page: str,
    selected_job_id: str | None,
    user_message: str,
    session_id: str | None = None,
    intent_classifier: KarenIntentClassifier | None = None,
    workflow_run_id: str | None = None,
) -> KarenChatTurnResult:
    """Persist and process one Karen chat turn."""

    initial_state: KarenGraphState = {
        "base_dir": Path(base_dir),
        "current_page": current_page,
        "selected_job_id": selected_job_id,
        "session_id": session_id,
        "user_message": user_message,
        "intent_classifier": intent_classifier,
        "workflow_run_id": workflow_run_id,
    }
    graph = build_karen_graph()
    result = graph.invoke(initial_state)
    return KarenChatTurnResult(
        assistant_message=result["assistant_message"],
        intent=result.get("intent"),
        tool_result=result.get("tool_result"),
        context=result["context"],
    )


def build_karen_graph():
    """Build Karen's LangGraph controller or a sequential fallback."""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialKarenGraph()

    graph = StateGraph(KarenGraphState)
    graph.add_node("build_context", _build_context_node)
    graph.add_node("persist_user", _persist_user_node)
    graph.add_node("classify_intent", _classify_intent_node)
    graph.add_node("apply_policy_and_tools", _apply_policy_and_tools_node)
    graph.add_node("persist_assistant", _persist_assistant_node)
    graph.set_entry_point("build_context")
    graph.add_edge("build_context", "persist_user")
    graph.add_edge("persist_user", "classify_intent")
    graph.add_edge("classify_intent", "apply_policy_and_tools")
    graph.add_edge("apply_policy_and_tools", "persist_assistant")
    graph.add_edge("persist_assistant", END)
    return graph.compile()


def classify_karen_intent_with_llm(
    context: KarenContext,
    user_message: str,
) -> KarenIntentResponse:
    """Classify one user message with the configured OpenAI provider."""

    prompts = _load_karen_prompts()
    system_prompt = _prompt(prompts, "runtime_system")
    user_prompt = _prompt(prompts, "intent_classification").format(
        context_json=context.model_dump_json(indent=2),
        user_message=user_message,
    )
    return llm_client.parse_structured_response(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text_format=KarenIntentResponse,
        operation="Karen intent classification",
        profile=llm_client.KAREN_INTENT_PROFILE,
    )


def classify_karen_workflow_intent_with_llm(
    context: KarenContext,
    user_message: str,
) -> WorkflowIntent:
    """Classify one user message into a structured workflow goal."""

    prompts = _load_karen_prompts()
    system_prompt = _prompt(prompts, "runtime_system")
    user_prompt = _prompt(prompts, "workflow_intent_classification").format(
        context_json=context.model_dump_json(indent=2),
        user_message=user_message,
    )
    return llm_client.parse_structured_response(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text_format=WorkflowIntent,
        operation="Karen intent classification",
        profile=llm_client.KAREN_INTENT_PROFILE,
    )


class _SequentialKarenGraph:
    def invoke(self, state: KarenGraphState) -> KarenGraphState:
        next_state = dict(state)
        next_state.update(_build_context_node(next_state))
        next_state.update(_persist_user_node(next_state))
        next_state.update(_classify_intent_node(next_state))
        next_state.update(_apply_policy_and_tools_node(next_state))
        next_state.update(_persist_assistant_node(next_state))
        return next_state


def _build_context_node(state: KarenGraphState) -> KarenGraphState:
    context = build_karen_context(
        state["base_dir"],
        current_page=state["current_page"],
        selected_job_id=state.get("selected_job_id"),
        session_id=state.get("session_id"),
    )
    return {"context": context}


def _persist_user_node(state: KarenGraphState) -> KarenGraphState:
    context = state["context"]
    append_agent_chat_message(
        state["base_dir"],
        AgentChatMessage(
            session_id=context.session_id,
            role="user",
            content=state["user_message"],
            job_id=context.selected_job_id,
        ),
    )
    return {}


def _classify_intent_node(state: KarenGraphState) -> KarenGraphState:
    classifier = state.get("intent_classifier") or classify_karen_intent_with_llm
    context = state["context"]
    try:
        intent = classifier(context, state["user_message"])
    except RuntimeError as exc:
        message = _llm_error_message(exc, context)
        log_agent_event(
            state["base_dir"],
            AgentWorkflowEvent(
                session_id=context.session_id,
                job_id=context.selected_job_id,
                action="karen_intent_classification",
                result="error",
                details={"error": str(exc)},
            ),
        )
        return {
            "intent": None,
            "tool_result": None,
            "assistant_message": message,
        }
    return {"intent": intent}


def _apply_policy_and_tools_node(state: KarenGraphState) -> KarenGraphState:
    if state.get("assistant_message"):
        return {}

    context = state["context"]
    intent = state["intent"]
    if intent is None:
        return {"assistant_message": "Karen could not classify that request."}

    if intent.workflow_intent is not None:
        workflow_result = run_karen_workflow_goal(
            state["base_dir"],
            session_id=context.session_id,
            selected_job_id=context.selected_job_id,
            intent=intent.workflow_intent,
            workflow_run_id=state.get("workflow_run_id"),
        )
        tool_result = _workflow_result_to_tool_result(workflow_result)
        return {
            "context": context,
            "tool_result": tool_result,
            "assistant_message": _workflow_assistant_message(workflow_result),
        }

    tool_name = intent.proposed_tool
    definition = get_karen_tool_definition(tool_name)
    if tool_name and definition is None:
        tool_result = KarenToolResult(
            tool_name=tool_name,
            status="error",
            message=f"Karen does not have a registered tool named {tool_name}.",
        )
        return {
            "tool_result": tool_result,
            "assistant_message": _combine_messages(intent.assistant_message, tool_result.message),
        }

    actual_permission = definition.permission_level if definition else intent.permission_level
    context = _apply_inline_permission_grant_if_requested(state, context, definition)
    decision = evaluate_karen_tool_request(
        tool_name=tool_name,
        permission_level=actual_permission,
        auto_execute=intent.auto_execute,
        user_message=state["user_message"],
        selected_job_id=context.selected_job_id,
        target_job_id=intent.target_job_id,
        job_permissions=context.job_permissions,
        requires_job_permission=bool(definition and definition.needs_permission),
    )
    if not decision.allowed:
        safety_reason = intent.safety_reason or decision.reason
        tool_result = (
            KarenToolResult(
                tool_name=tool_name,
                status="refused",
                message=safety_reason,
                event_details={"safety_reason": safety_reason},
            )
            if tool_name
            else None
        )
        _log_refusal(state, tool_name or "karen_chat", safety_reason)
        return {
            "context": context,
            "tool_result": tool_result,
            "assistant_message": _combine_messages(intent.assistant_message, safety_reason),
        }

    if not tool_name:
        return {"context": context, "assistant_message": intent.assistant_message}

    tool_result = execute_karen_tool(
        state["base_dir"],
        context,
        tool_name,
        target_job_id=intent.target_job_id,
        route_page=intent.route_page,
    )
    if _should_log_tool_result(tool_result):
        _log_tool_event(state, tool_result)
    assistant_message = intent.assistant_message
    if state.get("inline_permission_granted") and tool_result.status == "executed":
        assistant_message = "Granted selected-job permissions for this session."
    return {
        "context": context,
        "tool_result": tool_result,
        "assistant_message": _combine_messages(assistant_message, tool_result.message),
    }


def _persist_assistant_node(state: KarenGraphState) -> KarenGraphState:
    context = state["context"]
    intent = state.get("intent")
    tool_result = state.get("tool_result")
    proposed_actions = [intent.proposed_tool] if intent and intent.proposed_tool else []
    message_job_id = context.selected_job_id
    if tool_result is not None and tool_result.tool_name == "delete_job_data":
        message_job_id = None
    append_agent_chat_message(
        state["base_dir"],
        AgentChatMessage(
            session_id=context.session_id,
            role="assistant",
            content=state["assistant_message"],
            job_id=message_job_id,
            proposed_actions=proposed_actions,
            executed_action=(
                tool_result.tool_name
                if tool_result is not None and tool_result.status == "executed"
                else None
            ),
        ),
    )
    return {}


def _load_karen_prompts() -> dict[str, Any]:
    with KAREN_PROMPTS_PATH.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Karen prompt templates must be a mapping: {KAREN_PROMPTS_PATH}")
    return payload


def _prompt(prompts: dict[str, Any], name: str) -> str:
    value = prompts.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"Karen prompt template must be a string: {name}")
    return value


def _llm_error_message(exc: RuntimeError, context: KarenContext) -> str:
    text = str(exc)
    state_lines = [
        f"Selected job: {context.selected_job_id or 'None'}.",
        f"Pending gate: {context.pending_gate or 'None'}.",
    ]
    if context.blockers:
        state_lines.append("Current blockers: " + "; ".join(context.blockers) + ".")
    if context.next_allowed_actions:
        state_lines.append(
            "Next allowed actions: " + "; ".join(context.next_allowed_actions) + "."
        )
    state_summary = " ".join(state_lines)
    if "OPENAI_API_KEY" in text:
        return (
            "Karen needs OPENAI_API_KEY to answer chat requests with the configured "
            "LLM. Your message was saved, and no workflow action was executed.\n\n"
            f"{state_summary}"
        )
    return f"Karen could not process that chat request: {text}\n\n{state_summary}"


def _combine_messages(primary: str, secondary: str) -> str:
    primary_text = primary.strip()
    secondary_text = secondary.strip()
    if not primary_text:
        return secondary_text
    if not secondary_text or secondary_text in primary_text:
        return primary_text
    return f"{primary_text}\n\n{secondary_text}"


def _workflow_assistant_message(result: WorkflowRunResult) -> str:
    """Return concise chat copy for deterministic workflow-controller turns."""

    lines = [_sentence(result.message)]
    blocker_text = _joined_blockers(result.blockers)
    if blocker_text and blocker_text.casefold() not in lines[0].casefold():
        lines.append(f"Blocked: {blocker_text}")

    next_line = _workflow_next_line(result)
    if next_line:
        lines.append(next_line)

    return "\n\n".join(line for line in lines if line)


def _workflow_next_line(result: WorkflowRunResult) -> str:
    if result.executed_actions and result.executed_actions[-1] == "launch_browser_use":
        return ""
    if result.status == "waiting_for_review" and result.pending_gate:
        return f"Needs review: {_gate_label(result.pending_gate)}"
    if result.status in {"blocked", "needs_input", "refused"}:
        return ""
    if result.pending_gate:
        return f"Next: {_gate_label(result.pending_gate)}"
    if result.next_allowed_actions:
        return "Next: " + ", ".join(
            ACTION_LABELS.get(action, action.replace("_", " ").title())
            for action in result.next_allowed_actions[:3]
        )
    return ""


def _gate_label(gate: str) -> str:
    return GATE_LABELS.get(gate, gate.replace("_", " ").title())


def _joined_blockers(blockers: list[str]) -> str:
    return "; ".join(blocker.strip().rstrip(".") for blocker in blockers if blocker.strip())


def _sentence(text: str) -> str:
    value = text.strip()
    if not value:
        return "Workflow checked."
    if value.endswith((".", "!", "?")):
        return value
    return f"{value}."


def _workflow_result_to_tool_result(result: WorkflowRunResult) -> KarenToolResult:
    details: dict[str, object] = {
        "status": result.status,
        "executed_actions": result.executed_actions,
        "pending_gate": result.pending_gate or "",
        "next_allowed_actions": result.next_allowed_actions,
        "selected_job_id": result.selected_job_id or "",
    }
    details.update(result.event_details)
    return KarenToolResult(
        tool_name="workflow_controller",
        status=result.status,
        message=result.message,
        blockers=result.blockers,
        executed_actions=result.executed_actions,
        pending_gate=result.pending_gate,
        next_allowed_actions=result.next_allowed_actions,
        selected_job_id=result.selected_job_id,
        artifact_paths=result.artifact_paths,
        route_hint=result.route_hint,
        event_details=details,
    )


def _should_log_tool_result(tool_result: KarenToolResult) -> bool:
    return tool_result.status in {
        "answered",
        "error",
        "executed",
        "needs_input",
        "needs_job",
        "refused",
        "routed",
    }


def _apply_inline_permission_grant_if_requested(
    state: KarenGraphState,
    context: KarenContext,
    definition: object,
) -> KarenContext:
    intent = state.get("intent")
    grant_intent = intent.permission_grant if intent is not None else None
    if grant_intent is None or not grant_intent.grant_selected_job_permissions:
        return context
    if (
        definition is not None
        and getattr(definition, "name", None)
        == "grant_job_session_permission"
    ):
        return context
    if not context.selected_job_id:
        return context

    session = grant_job_session_permission(
        state["base_dir"],
        session_id=context.session_id,
        job_id=context.selected_job_id,
        allow_app_mutations=grant_intent.allow_app_mutations,
        allow_browser_launch=grant_intent.allow_browser_launch,
    )
    granted_context = context.model_copy(
        update={"job_permissions": session.job_permissions},
    )
    state["context"] = granted_context
    state["inline_permission_granted"] = True
    log_agent_event(
        state["base_dir"],
        AgentWorkflowEvent(
            session_id=context.session_id,
            job_id=context.selected_job_id,
            action="grant_job_session_permission",
            result="executed",
            details={
                "source": "inline_chat_permission",
                "allow_app_mutations": grant_intent.allow_app_mutations,
                "allow_browser_launch": grant_intent.allow_browser_launch,
            },
        ),
    )
    return granted_context


def _log_refusal(state: KarenGraphState, action: str, safety_reason: str) -> None:
    context = state["context"]
    log_agent_event(
        state["base_dir"],
        AgentWorkflowEvent(
            session_id=context.session_id,
            job_id=context.selected_job_id,
            action=action,
            result="refused",
            details={"safety_reason": safety_reason},
        ),
    )


def _log_tool_event(state: KarenGraphState, tool_result: KarenToolResult) -> None:
    context = state["context"]
    job_id = None if tool_result.tool_name == "delete_job_data" else context.selected_job_id
    log_agent_event(
        state["base_dir"],
        AgentWorkflowEvent(
            session_id=context.session_id,
            job_id=job_id,
            action=tool_result.tool_name,
            result=tool_result.status,
            artifact_paths=tool_result.artifact_paths,
            details=tool_result.event_details,
        ),
    )
