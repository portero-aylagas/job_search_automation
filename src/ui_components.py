"""Reusable Streamlit display helpers for workflow evidence and summaries."""

from __future__ import annotations

import streamlit as st

from src.schemas import AIWorkflowTrace


def render_artifact_traceability(metadata: dict[str, object]) -> None:
    """Render artifact traceability metadata when available."""

    traceability = metadata.get("traceability")
    if not isinstance(traceability, dict):
        return

    source_requirements = traceability.get("source_requirements")
    source_experience_units = traceability.get("source_experience_units")
    if not source_requirements and not source_experience_units:
        return

    st.markdown("**Traceability**")
    if isinstance(source_requirements, list) and source_requirements:
        st.caption("Source requirements")
        for requirement in source_requirements:
            if not isinstance(requirement, dict):
                continue
            label = requirement.get("label") or requirement.get("evidence") or "Requirement"
            confidence = requirement.get("confidence") or "unknown"
            st.write(f"- {label} (confidence: {confidence})")
            if requirement.get("evidence"):
                st.caption(str(requirement["evidence"]))

    if isinstance(source_experience_units, list) and source_experience_units:
        st.caption("Source experience")
        for experience in source_experience_units:
            if not isinstance(experience, dict):
                continue
            label = experience.get("title") or experience.get("id") or "Experience"
            organization = experience.get("organization")
            st.write(f"- {label}{f' / {organization}' if organization else ''}")


def render_requirement_findings(
    label: str,
    findings: list,
) -> None:
    """Render a list of evidence-backed requirement findings."""

    if not findings:
        return
    st.markdown(f"**{label}**")
    for finding in findings:
        required = "required" if finding.required else "optional or unclear"
        constraints = (
            f" Constraints: {', '.join(finding.constraints)}" if finding.constraints else ""
        )
        st.write(f"- {finding.label} ({required}, confidence: {finding.confidence}).{constraints}")
        if finding.evidence:
            st.caption(finding.evidence)


def render_form_fields(label: str, fields: list) -> None:
    """Render application form fields discovered from the apply page."""

    if not fields:
        return
    st.markdown(f"**{label}**")
    for field in fields:
        required = "required" if field.required else "optional or unclear"
        options = f" Options: {', '.join(field.options)}" if field.options else ""
        st.write(
            f"- {field.label} ({field.input_type or 'field'}, {required}, "
            f"confidence: {field.confidence}).{options}"
        )
        if field.evidence:
            st.caption(field.evidence)


def render_screening_questions(
    label: str,
    questions: list,
) -> None:
    """Render discovered screening questions."""

    if not questions:
        return
    st.markdown(f"**{label}**")
    for question in questions:
        required = "required" if question.required else "optional or unclear"
        st.write(
            f"- {question.question} ({question.input_type or 'field'}, {required}, "
            f"confidence: {question.confidence})"
        )
        if question.evidence:
            st.caption(question.evidence)


def render_field(label: str, value: str | None) -> None:
    """Render one label/value pair."""

    st.markdown(f"**{label}**")
    st.write(value or "Not specified")


def build_ai_usage_summary(
    traces: list[AIWorkflowTrace | None],
) -> dict[str, int]:
    """Aggregate AI workflow traces into usage counters for review."""

    active_traces = [trace for trace in traces if trace is not None]
    return {
        "call_count": len(active_traces),
        "attempt_count": sum(trace.attempt_count for trace in active_traces),
        "retry_count": sum(max(trace.attempt_count - 1, 0) for trace in active_traces),
        "output_token_budget": sum(
            trace.max_output_tokens * trace.attempt_count for trace in active_traces
        ),
        "worst_case_output_token_budget": sum(
            trace.max_output_tokens * (trace.max_retries + 1) for trace in active_traces
        ),
        "tool_call_cap": sum(trace.max_tool_calls or 0 for trace in active_traces),
    }


def render_ai_usage_summary(label: str, traces: list[AIWorkflowTrace | None]) -> None:
    """Render summarized AI usage for visible workflow traceability."""

    summary = build_ai_usage_summary(traces)
    if summary["call_count"] == 0:
        return

    with st.expander(label, expanded=False):
        st.write(f"AI calls: {summary['call_count']}")
        st.write(f"Provider attempts: {summary['attempt_count']}")
        st.write(f"Retries used: {summary['retry_count']}")
        st.write(f"Output token budget used by attempts: {summary['output_token_budget']}")
        st.write(
            "Worst-case output token budget with configured retries: "
            f"{summary['worst_case_output_token_budget']}"
        )
        st.write(f"Tool call cap: {summary['tool_call_cap'] or 'none'}")


def render_workflow_trace(label: str, trace: AIWorkflowTrace | None) -> None:
    """Render detailed AI workflow trace metadata when present."""

    if trace is None:
        return

    with st.expander(label, expanded=False):
        st.write(f"Workflow: {trace.workflow_name}")
        st.write(f"Operation: {trace.operation}")
        st.write(f"Model: {trace.model}")
        st.write(f"Profile: {trace.profile_name}")
        st.write(f"Temperature: {trace.temperature}")
        st.write(f"Max output tokens: {trace.max_output_tokens}")
        st.write(f"Timeout seconds: {trace.timeout_seconds}")
        st.write(f"Retries allowed: {trace.max_retries}")
        st.write(f"Retry backoff seconds: {trace.retry_backoff_seconds}")
        st.write(f"Tool call cap: {trace.max_tool_calls or 'none'}")
        st.write(f"Attempt count: {trace.attempt_count}")
        st.write(f"Duration (ms): {trace.duration_ms or 0}")
        st.caption(f"Recorded at {trace.recorded_at}")


def render_list(label: str, values: list[str]) -> None:
    """Render a labeled bullet list when values are available."""

    if not values:
        return
    st.markdown(f"**{label}**")
    for value in values:
        st.write(f"- {value}")


def render_additional_details(job_details: dict[str, object]) -> None:
    """Render dynamic and miscellaneous job details."""

    dynamic_fields = job_details.get("dynamic_fields")
    rendered_any = False

    if isinstance(dynamic_fields, list):
        st.markdown("**Additional Extracted Details**")
        for field in dynamic_fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "Additional Detail")
            value = field.get("value")
            render_field(name, str(value) if value is not None else None)
            rendered_any = True

    remaining_details = {
        key: value
        for key, value in job_details.items()
        if key not in {"dynamic_fields", "extraction_confidence"} and value
    }
    if remaining_details:
        if not rendered_any:
            st.markdown("**Additional Extracted Details**")
        for key, value in remaining_details.items():
            render_field(key.replace("_", " ").title(), format_detail_value(value))


def format_detail_value(value: object) -> str:
    """Format an arbitrary job detail value for display."""

    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
