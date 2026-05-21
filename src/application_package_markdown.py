"""Markdown export rendering for generated application packages."""

from __future__ import annotations

from typing import Any

from src.schemas import ApplicationPackage, JobListing


def render_application_package_markdown(
    package: ApplicationPackage,
    job: JobListing,
) -> str:
    """Render an application package as a human-readable Markdown export."""

    lines = [
        f"# Application Package: {job.company} / {job.title}",
        "",
        f"- Job ID: {package.job_id}",
        f"- Package status: {package.status}",
        "",
    ]

    if package.selected_experience_units:
        lines.append("## Selected Experience Units")
        lines.extend(f"- {item}" for item in package.selected_experience_units)
        lines.append("")

    if package.missing_information:
        lines.append("## Missing Information")
        lines.extend(f"- {item}" for item in package.missing_information)
        lines.append("")

    for artifact in package.artifacts:
        required = "required" if artifact.required else "optional"
        lines.extend(
            [
                f"## {artifact.label}",
                "",
                f"- Type: {artifact.type}",
                f"- Status: {artifact.status}",
                f"- Requirement: {required}",
                "",
            ]
        )
        if artifact.source_prompt:
            lines.extend(["### Source Prompt", "", artifact.source_prompt, ""])
        if artifact.source_requirement:
            lines.extend(["### Source Requirement", "", artifact.source_requirement, ""])
        traceability_lines = _render_artifact_traceability_markdown(artifact.metadata)
        if traceability_lines:
            lines.extend(["### Traceability", "", *traceability_lines, ""])
        lines.extend([artifact.content or "_No content generated._", ""])

    if package.generation_notes:
        lines.append("## Generation Notes")
        lines.extend(f"- {item}" for item in package.generation_notes)
        lines.append("")

    if package.workflow_trace:
        lines.extend(
            [
                "## AI Run Metadata",
                "",
                f"- Workflow: {package.workflow_trace.workflow_name}",
                f"- Operation: {package.workflow_trace.operation}",
                f"- Model: {package.workflow_trace.model}",
                f"- Profile: {package.workflow_trace.profile_name}",
                f"- Attempts: {package.workflow_trace.attempt_count}",
                f"- Duration (ms): {package.workflow_trace.duration_ms or 0}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def _render_artifact_traceability_markdown(metadata: dict[str, Any]) -> list[str]:
    traceability = metadata.get("traceability")
    if not isinstance(traceability, dict):
        return []

    lines: list[str] = []
    source_requirements = traceability.get("source_requirements")
    if isinstance(source_requirements, list) and source_requirements:
        lines.append("Source requirements:")
        for requirement in source_requirements:
            if isinstance(requirement, dict):
                label = requirement.get("label") or requirement.get("evidence") or "Requirement"
                confidence = requirement.get("confidence") or "unknown"
                lines.append(f"- {label} (confidence: {confidence})")

    source_experience_units = traceability.get("source_experience_units")
    if isinstance(source_experience_units, list) and source_experience_units:
        if lines:
            lines.append("")
        lines.append("Source experience:")
        for experience in source_experience_units:
            if isinstance(experience, dict):
                label = experience.get("title") or experience.get("id") or "Experience"
                organization = experience.get("organization")
                lines.append(f"- {label}{f' / {organization}' if organization else ''}")
    return lines
