"""Traceability metadata helpers for generated application packages."""

from __future__ import annotations

from typing import Any

from src.schemas import (
    AIWorkflowTrace,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ExperienceUnit,
)


def attach_application_package_traceability(
    package: ApplicationPackage,
    requirements: ApplicationRequirements | None,
    experience_units: list[ExperienceUnit],
) -> ApplicationPackage:
    """Attach requirement and experience-unit traceability metadata to artifacts."""

    traced_package = package.model_copy(deep=True)
    selected_experience = _selected_experience_trace(
        traced_package.selected_experience_units,
        experience_units,
    )
    requirement_traces = _requirement_trace_entries(requirements)

    for artifact in traced_package.artifacts:
        source_requirements = _matching_requirement_traces(
            artifact.type,
            artifact.source_prompt,
            artifact.source_requirement,
            requirement_traces,
            requirements,
        )
        metadata = dict(artifact.metadata)
        metadata["traceability"] = {
            "source_requirements": source_requirements,
            "source_experience_units": selected_experience,
        }
        provenance = _artifact_provenance(metadata)
        provenance["workflow_trace"] = _workflow_trace_metadata(traced_package.workflow_trace)
        provenance["source_requirements"] = source_requirements
        provenance["source_experience_units"] = selected_experience
        metadata["provenance"] = provenance
        artifact.metadata = metadata

    return traced_package


def _artifact_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    provenance = metadata.get("provenance")
    if isinstance(provenance, dict):
        return dict(provenance)
    return {}


def _workflow_trace_metadata(trace: AIWorkflowTrace | None) -> dict[str, Any] | None:
    if trace is None:
        return None

    return {
        "workflow_name": trace.workflow_name,
        "operation": trace.operation,
        "model": trace.model,
        "profile_name": trace.profile_name,
        "temperature": trace.temperature,
        "max_output_tokens": trace.max_output_tokens,
        "timeout_seconds": trace.timeout_seconds,
        "max_retries": trace.max_retries,
        "max_tool_calls": trace.max_tool_calls,
        "truncation": trace.truncation,
        "attempt_count": trace.attempt_count,
        "duration_ms": trace.duration_ms,
        "prompt_template_name": trace.prompt_template_name,
        "prompt_template_version": trace.prompt_template_version,
        "prompt_template_hash": trace.prompt_template_hash,
    }


def _selected_experience_trace(
    selected_ids: list[str],
    experience_units: list[ExperienceUnit],
) -> list[dict[str, Any]]:
    experience_by_id = {unit.id: unit for unit in experience_units}
    traces: list[dict[str, Any]] = []
    for selected_id in selected_ids:
        unit = experience_by_id.get(selected_id)
        if unit is None:
            traces.append({"id": selected_id})
            continue
        traces.append(
            {
                "id": unit.id,
                "title": unit.title,
                "organization": unit.organization,
                "summary": unit.summary,
                "skills": unit.skills,
                "evidence_points": unit.evidence_points,
            }
        )
    return traces


def _requirement_trace_entries(
    requirements: ApplicationRequirements | None,
) -> list[dict[str, str]]:
    if requirements is None:
        return []

    traces: list[dict[str, str]] = []
    for kind, findings in (
        ("required_document", requirements.required_documents),
        ("upload_expectation", requirements.upload_expectations),
        ("consent_requirement", requirements.consent_requirements),
        ("privacy_login_ats_gate", requirements.privacy_login_ats_gates),
        ("deadline", requirements.deadlines),
        ("contact_or_fallback", requirements.contact_or_fallback),
    ):
        traces.extend(_finding_trace(kind, finding) for finding in findings)

    if requirements.motivation_letter is not None:
        traces.append(_finding_trace("motivation_letter", requirements.motivation_letter))

    traces.extend(
        {
            "kind": "screening_question",
            "label": question.question,
            "evidence": question.evidence,
            "confidence": question.confidence,
        }
        for question in requirements.screening_questions
    )
    traces.extend(
        {
            "kind": "custom_form_field",
            "label": field.label or field.name,
            "evidence": field.evidence,
            "confidence": field.confidence,
        }
        for field in requirements.custom_form_fields
    )
    traces.extend(
        {
            "kind": "missing_or_uncertain",
            "label": item,
            "evidence": item,
            "confidence": "low",
        }
        for item in requirements.missing_or_uncertain
    )
    return traces


def _finding_trace(
    kind: str,
    finding: ApplicationRequirementFinding,
) -> dict[str, str]:
    return {
        "kind": kind,
        "label": finding.label,
        "evidence": finding.evidence,
        "confidence": finding.confidence,
    }


def _matching_requirement_traces(
    artifact_type: str,
    source_prompt: str | None,
    source_requirement: str | None,
    requirement_traces: list[dict[str, str]],
    requirements: ApplicationRequirements | None,
) -> list[dict[str, str]]:
    if not requirement_traces:
        return []

    selected = [
        trace
        for trace in requirement_traces
        if _trace_matches_source(trace, source_prompt, source_requirement)
    ]
    if selected:
        return selected

    if artifact_type == "cover_letter" and requirements and requirements.motivation_letter:
        return [
            trace for trace in requirement_traces if trace["kind"] == "motivation_letter"
        ]
    if artifact_type == "document_upload_checklist":
        return [
            trace
            for trace in requirement_traces
            if trace["kind"] in {"required_document", "upload_expectation"}
        ]
    if artifact_type == "missing_information_checklist":
        return [
            trace for trace in requirement_traces if trace["kind"] == "missing_or_uncertain"
        ]
    return []


def _trace_matches_source(
    trace: dict[str, str],
    source_prompt: str | None,
    source_requirement: str | None,
) -> bool:
    source_text = " ".join(
        item.casefold()
        for item in (source_prompt or "", source_requirement or "")
        if item
    )
    if not source_text:
        return False
    return any(
        value and value.casefold() in source_text
        for value in (trace["label"], trace["evidence"])
    )
