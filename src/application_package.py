from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src import llm_client
from src.paths import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME as _APPLICATION_PACKAGE_MARKDOWN_FILENAME,
)
from src.paths import (
    application_package_markdown_path,
    application_package_paths,
    runtime_application_package_path,
    runtime_jobs_index_path,
    runtime_tracker_path,
)
from src.prompt_templates import get_prompt
from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    TrackerRecord,
)
from src.storage import load_model, save_model

APPLICATION_PACKAGE_MARKDOWN_FILENAME = _APPLICATION_PACKAGE_MARKDOWN_FILENAME

PackageGenerator = Callable[
    [CandidateProfile, list[ExperienceUnit], JobListing, ApplicationRequirements | None],
    ApplicationPackage,
]


class ApplicationArtifactManifestItem(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    source_prompt: str | None = None
    source_requirement: str | None = None


class LLMApplicationArtifact(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    status: Literal["draft", "needs_review"] = "draft"
    content: str = ""
    source_prompt: str | None = None
    source_requirement: str | None = None


class LLMApplicationPackageResponse(BaseModel):
    job_id: str = ""
    status: Literal["draft", "needs_review"] = "draft"
    artifacts: list[LLMApplicationArtifact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    selected_experience_units: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)


def generate_application_package(
    candidate_profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
    *,
    generator: PackageGenerator | None = None,
) -> ApplicationPackage:
    selected_generator = generator or generate_application_package_with_fallback
    package = selected_generator(candidate_profile, experience_units, job, requirements)
    package = attach_application_package_traceability(package, requirements, experience_units)
    package = apply_application_package_quality_checks(
        package,
        candidate_profile,
        job,
    )
    return normalize_application_package(job, package)


def generate_application_package_with_fallback(
    candidate_profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
) -> ApplicationPackage:
    """Generate a package with the LLM and fall back to templates if unavailable."""

    try:
        return generate_application_package_with_llm(
            candidate_profile,
            experience_units,
            job,
            requirements,
        )
    except RuntimeError as exc:
        return generate_application_package_from_template(
            candidate_profile,
            experience_units,
            job,
            requirements,
            fallback_reason=str(exc),
        )


def generate_application_package_from_template(
    candidate_profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
    *,
    fallback_reason: str = "",
) -> ApplicationPackage:
    """Generate reviewable package artifacts without calling an external LLM."""

    manifest = build_application_artifact_manifest(job, requirements)
    missing_information = build_missing_information_defaults(candidate_profile, requirements)
    selected_experience_ids = _select_template_experience_units(job, experience_units)
    selected_experience = [
        unit for unit in experience_units if unit.id in set(selected_experience_ids)
    ]
    artifacts = [
        ApplicationArtifact(
            id=item.id,
            type=item.type,
            label=item.label,
            required=item.required,
            status="needs_review",
            content=_template_artifact_content(
                item,
                candidate_profile,
                selected_experience,
                job,
                requirements,
                missing_information,
            ),
            source_prompt=item.source_prompt,
            source_requirement=item.source_requirement,
        )
        for item in manifest
    ]
    notes = ["Template fallback generated this package without a live AI response."]
    if fallback_reason.strip():
        notes.append(f"Fallback reason: {fallback_reason.strip()}")

    return ApplicationPackage(
        job_id=job.id,
        status="needs_review",
        artifacts=artifacts,
        missing_information=missing_information,
        selected_experience_units=selected_experience_ids,
        generation_notes=notes,
    )


def build_application_artifact_manifest(
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
) -> list[ApplicationArtifactManifestItem]:
    manifest = [
        ApplicationArtifactManifestItem(
            id="application-summary",
            type="application_summary",
            label="Application Summary",
            required=True,
        ),
        ApplicationArtifactManifestItem(
            id="positioning-strategy",
            type="positioning_strategy",
            label="Positioning Strategy",
            required=True,
        ),
        ApplicationArtifactManifestItem(
            id="cv-tailoring-notes",
            type="cv_tailoring_notes",
            label="CV Tailoring Notes",
            required=True,
        ),
        ApplicationArtifactManifestItem(
            id="missing-information-checklist",
            type="missing_information_checklist",
            label="Missing Information Checklist",
            required=True,
        ),
    ]

    if requirements is None:
        return manifest

    if requirements.motivation_letter or _requirements_hint_at_cover_letter(job, requirements):
        manifest.append(
            ApplicationArtifactManifestItem(
                id="cover-letter-draft",
                type="cover_letter",
                label="Cover Letter Draft",
                required=bool(
                    requirements.motivation_letter
                    and requirements.motivation_letter.required
                ),
                source_requirement=(
                    requirements.motivation_letter.label if requirements.motivation_letter else None
                ),
            )
        )

    if requirements.required_documents or requirements.upload_expectations:
        manifest.append(
            ApplicationArtifactManifestItem(
                id="document-upload-checklist",
                type="document_upload_checklist",
                label="Document / Upload Checklist",
                required=any(
                    item.required
                    for item in [
                        *requirements.required_documents,
                        *requirements.upload_expectations,
                    ]
                ),
            )
        )

    for index, question in enumerate(requirements.screening_questions, start=1):
        if _is_sensitive_or_user_decision_field(question.question):
            continue
        manifest.append(
            ApplicationArtifactManifestItem(
                id=f"screening-question-{index}",
                type="form_answer",
                label=f"Screening Answer {index}",
                required=question.required,
                source_prompt=question.question,
                source_requirement=question.evidence or question.question,
            )
        )

    for index, field in enumerate(requirements.custom_form_fields, start=1):
        if _is_sensitive_or_user_decision_field(field.label):
            continue
        manifest.append(
            ApplicationArtifactManifestItem(
                id=f"custom-field-{index}",
                type="form_answer",
                label=field.label or f"Custom Field {index}",
                required=field.required,
                source_prompt=field.label,
                source_requirement=field.evidence or field.label,
            )
        )

    if requirements.contact_or_fallback:
        manifest.append(
            ApplicationArtifactManifestItem(
                id="recruiter-message-draft",
                type="recruiter_message",
                label="Recruiter Message Draft",
                required=False,
                source_requirement=", ".join(
                    item.label for item in requirements.contact_or_fallback
                ),
            )
        )

    return manifest


def build_missing_information_defaults(
    candidate_profile: CandidateProfile,
    requirements: ApplicationRequirements | None,
) -> list[str]:
    missing: list[str] = []
    profile_data = candidate_profile.candidate_profile
    identity = profile_data.cv_extracted.identity

    if not identity.full_name.strip():
        missing.append("Candidate full name is missing.")
    if not identity.email.strip():
        missing.append("Candidate email is missing.")
    if not profile_data.source_documents.cv.file_path.strip():
        missing.append("Candidate CV file is missing.")
    if not profile_data.candidate_preferences.target_locations:
        missing.append("Candidate target locations are missing.")

    if requirements is None:
        missing.append("Application requirements have not been discovered for this job.")
        return missing

    for question in requirements.screening_questions:
        if _is_sensitive_or_user_decision_field(question.question):
            missing.append(f"User decision required: {question.question}")

    for field in [*requirements.custom_form_fields, *requirements.profile_fields]:
        label = field.label or field.name
        if _is_sensitive_or_user_decision_field(label):
            missing.append(f"User decision required: {label}")

    for requirement in requirements.consent_requirements:
        if requirement.required:
            missing.append(f"User must review consent requirement: {requirement.label}")

    missing.extend(requirements.missing_or_uncertain)
    return _dedupe(missing)


def generate_application_package_with_llm(
    candidate_profile: CandidateProfile,
    experience_units: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
) -> ApplicationPackage:
    manifest = build_application_artifact_manifest(job, requirements)
    missing_defaults = build_missing_information_defaults(candidate_profile, requirements)
    requirements_json = _to_json(requirements) if requirements else "Not discovered."
    workflow_trace: AIWorkflowTrace | None = None

    def capture_trace(trace: AIWorkflowTrace) -> None:
        nonlocal workflow_trace
        workflow_trace = trace

    response = llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": get_prompt("application_package", "generate_package", "system"),
            },
            {
                "role": "user",
                "content": get_prompt(
                    "application_package",
                    "generate_package",
                    "user",
                    manifest_json=_to_json(manifest),
                    missing_defaults_json=_to_json(missing_defaults),
                    candidate_profile_json=_to_json(candidate_profile),
                    experience_units_json=_to_json(experience_units),
                    job_json=_to_json(job),
                    requirements_json=requirements_json,
                ),
            },
        ],
        text_format=LLMApplicationPackageResponse,
        operation="AI package generation",
        # This is the one workflow where some phrasing flexibility is useful.
        profile=llm_client.APPLICATION_PACKAGE_PROFILE,
        trace_sink=capture_trace,
    )

    payload = response.model_dump(mode="json")
    payload["job_id"] = job.id
    payload["missing_information"] = _dedupe(
        [*missing_defaults, *payload.get("missing_information", [])]
    )
    package = ApplicationPackage.model_validate(payload)
    package.workflow_trace = workflow_trace
    package = attach_application_package_traceability(package, requirements, experience_units)
    return apply_application_package_quality_checks(package, candidate_profile, job)


def attach_application_package_traceability(
    package: ApplicationPackage,
    requirements: ApplicationRequirements | None,
    experience_units: list[ExperienceUnit],
) -> ApplicationPackage:
    traced_package = package.model_copy(deep=True)
    selected_experience = _selected_experience_trace(
        traced_package.selected_experience_units,
        experience_units,
    )
    requirement_traces = _requirement_trace_entries(requirements)

    for artifact in traced_package.artifacts:
        metadata = dict(artifact.metadata)
        metadata["traceability"] = {
            "source_requirements": _matching_requirement_traces(
                artifact.type,
                artifact.source_prompt,
                artifact.source_requirement,
                requirement_traces,
                requirements,
            ),
            "source_experience_units": selected_experience,
        }
        artifact.metadata = metadata

    return traced_package


def apply_application_package_quality_checks(
    package: ApplicationPackage,
    candidate_profile: CandidateProfile,
    job: JobListing,
) -> ApplicationPackage:
    checked_package = package.model_copy(deep=True)
    candidate_evidence = _candidate_evidence_text(candidate_profile)
    unsupported_terms = _unsupported_requirement_terms(job, candidate_evidence)
    review_items: list[str] = []

    for artifact in checked_package.artifacts:
        findings = [
            *_sensitive_answer_findings(artifact),
            *_unsupported_claim_findings(artifact.content, unsupported_terms),
        ]
        if not findings:
            continue

        metadata = dict(artifact.metadata)
        metadata["quality_findings"] = _dedupe(
            [
                *[str(item) for item in metadata.get("quality_findings", [])],
                *findings,
            ]
        )
        artifact.metadata = metadata
        if artifact.status != "manually_edited":
            artifact.status = "needs_review"
        review_items.extend(
            f"Review generated artifact '{artifact.label}': {finding}"
            for finding in findings
        )

    if review_items:
        checked_package.status = "needs_review"
        checked_package.missing_information = _dedupe(
            [*checked_package.missing_information, *review_items]
        )
        checked_package.generation_notes = _dedupe(
            [
                *checked_package.generation_notes,
                "Quality checks flagged generated content for reviewer confirmation.",
            ]
        )
    return checked_package


def normalize_application_package(
    job: JobListing,
    package: ApplicationPackage,
) -> ApplicationPackage:
    payload = package.model_dump(mode="json")
    payload["job_id"] = job.id
    payload["status"] = payload.get("status") or "draft"
    payload["missing_information"] = _dedupe(payload.get("missing_information", []))
    payload["selected_experience_units"] = _dedupe(payload.get("selected_experience_units", []))

    normalized_artifacts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, artifact in enumerate(payload.get("artifacts", []), start=1):
        artifact_id = str(artifact.get("id") or f"artifact-{index}")
        artifact_id = _unique_id(slugify(artifact_id), seen_ids)
        seen_ids.add(artifact_id)
        normalized = dict(artifact)
        normalized["id"] = artifact_id
        normalized["status"] = normalized.get("status") or "draft"
        normalized["content"] = str(normalized.get("content") or "").strip()
        normalized_artifacts.append(normalized)

    payload["artifacts"] = normalized_artifacts
    return ApplicationPackage.model_validate(payload)


def apply_manual_artifact_edits(
    package: ApplicationPackage,
    edits_by_artifact_id: dict[str, str],
) -> ApplicationPackage:
    edited_package = package.model_copy(deep=True)
    edited_labels: list[str] = []

    for artifact in edited_package.artifacts:
        if artifact.id not in edits_by_artifact_id:
            continue
        edited_content = str(edits_by_artifact_id[artifact.id]).strip()
        if edited_content == artifact.content:
            continue
        artifact.content = edited_content
        artifact.status = "manually_edited"
        metadata = dict(artifact.metadata)
        metadata["manual_edit"] = True
        artifact.metadata = metadata
        edited_labels.append(artifact.label)

    if edited_labels:
        edited_package.generation_notes = _dedupe(
            [
                *edited_package.generation_notes,
                "Manual edits saved for: " + ", ".join(edited_labels),
            ]
        )
    return edited_package


def reject_application_package(
    package: ApplicationPackage,
    reason: str = "",
) -> ApplicationPackage:
    rejected_package = package.model_copy(deep=True)
    rejected_package.status = "rejected"
    normalized_reason = reason.strip() or "No reason provided."
    rejected_package.generation_notes = _dedupe(
        [
            *rejected_package.generation_notes,
            f"Rejected by reviewer: {normalized_reason}",
        ]
    )
    return rejected_package


def render_application_package_markdown(
    package: ApplicationPackage,
    job: JobListing,
) -> str:
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


def save_application_package(
    base_dir: Path | str,
    package: ApplicationPackage,
    job: JobListing,
) -> tuple[Path, Path]:
    json_path = runtime_application_package_path(base_dir, package.job_id)
    markdown_path = application_package_markdown_path(base_dir, package.job_id)
    save_model(json_path, package)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_application_package_markdown(package, job), encoding="utf-8")
    return json_path, markdown_path


def load_application_package(
    base_dir: Path | str,
    job_id: str,
) -> ApplicationPackage | None:
    runtime_path, template_path = application_package_paths(base_dir, job_id)
    if runtime_path.exists():
        return load_model(runtime_path, ApplicationPackage, default=None)
    if template_path.exists():
        return load_model(template_path, ApplicationPackage, default=None)
    return None


def update_tracker_for_application_package(
    base_dir: Path | str,
    job_id: str,
    package_path: Path | str,
) -> list[TrackerRecord]:
    jobs_index_path = runtime_jobs_index_path(base_dir)
    tracker_path = runtime_tracker_path(base_dir)
    tracker_records = load_model(jobs_index_path, list[TrackerRecord], default=[])
    package_path_text = str(package_path)

    for record in tracker_records:
        if record.job_id != job_id:
            continue
        record.status = "application_draft"
        record.generated_package_path = package_path_text
        break

    save_model(jobs_index_path, tracker_records)
    save_model(tracker_path, tracker_records)
    return tracker_records


def _template_artifact_content(
    manifest_item: ApplicationArtifactManifestItem,
    candidate_profile: CandidateProfile,
    selected_experience: list[ExperienceUnit],
    job: JobListing,
    requirements: ApplicationRequirements | None,
    missing_information: list[str],
) -> str:
    candidate_name = _candidate_display_name(candidate_profile)
    evidence_lines = _template_evidence_lines(selected_experience)
    matched_skills = _template_matched_skills(job, selected_experience)

    if manifest_item.type == "application_summary":
        return "\n".join(
            [
                f"{candidate_name} is preparing an application for {job.title} at {job.company}.",
                _job_context_sentence(job),
                _matched_skills_sentence(matched_skills),
                "Review this summary before using it in an application.",
            ]
        )
    if manifest_item.type == "positioning_strategy":
        return "\n".join(
            [
                "Position the application around these grounded points:",
                *evidence_lines,
                _matched_skills_sentence(matched_skills),
            ]
        )
    if manifest_item.type == "cv_tailoring_notes":
        return "\n".join(
            [
                "CV tailoring notes:",
                *evidence_lines,
                (
                    "Keep claims limited to evidence from the candidate profile "
                    "and selected experience units."
                ),
            ]
        )
    if manifest_item.type == "missing_information_checklist":
        checklist = missing_information or [
            "No missing information identified by the template fallback."
        ]
        return "\n".join(["Missing information to review:", *[f"- {item}" for item in checklist]])
    if manifest_item.type == "cover_letter":
        return "\n".join(
            [
                f"Dear {job.company} hiring team,",
                "",
                (
                    f"I am interested in the {job.title} role. My background is strongest "
                    "where it connects to the documented requirements and the experience "
                    "evidence below:"
                ),
                *evidence_lines,
                _matched_skills_sentence(matched_skills),
                "",
                "Please review and tailor this draft before submission.",
            ]
        )
    if manifest_item.type == "document_upload_checklist":
        return _template_document_checklist(requirements)
    if manifest_item.type == "form_answer":
        prompt = manifest_item.source_prompt or manifest_item.label
        return "\n".join(
            [
                f"Question or field: {prompt}",
                "Draft answer:",
                _template_form_answer(job, selected_experience, matched_skills),
                "Review this answer before submission.",
            ]
        )
    if manifest_item.type == "recruiter_message":
        return "\n".join(
            [
                f"Hello, I am interested in the {job.title} role at {job.company}.",
                _matched_skills_sentence(matched_skills),
                "I would appreciate guidance on the best application path for this position.",
            ]
        )

    return "Template fallback created this artifact. Review and complete it before submission."


def _select_template_experience_units(
    job: JobListing,
    experience_units: list[ExperienceUnit],
) -> list[str]:
    scored_units = [
        (_template_experience_score(job, unit), unit.id)
        for unit in experience_units
    ]
    positive_matches = [
        unit_id
        for score, unit_id in sorted(scored_units, reverse=True)
        if score > 0
    ]
    if positive_matches:
        return positive_matches[:3]
    return [unit.id for unit in experience_units[:2]]


def _template_experience_score(job: JobListing, unit: ExperienceUnit) -> int:
    job_terms = _template_keywords(
        [job.title, job.description or "", *job.requirements, *job.nice_to_have_skills]
    )
    unit_terms = _template_keywords(
        [unit.title, unit.summary, *unit.skills, *unit.evidence_points]
    )
    return len(job_terms & unit_terms)


def _template_keywords(values: list[str]) -> set[str]:
    stopwords = {
        "and",
        "for",
        "the",
        "with",
        "you",
        "your",
        "this",
        "that",
        "role",
        "job",
    }
    words = {
        word
        for value in values
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) > 2 and word not in stopwords
    }
    return words


def _candidate_display_name(candidate_profile: CandidateProfile) -> str:
    full_name = candidate_profile.candidate_profile.cv_extracted.identity.full_name.strip()
    return full_name or "The candidate"


def _template_evidence_lines(experience_units: list[ExperienceUnit]) -> list[str]:
    if not experience_units:
        return ["- No reusable experience units were available for this draft."]

    lines: list[str] = []
    for unit in experience_units:
        evidence = unit.evidence_points[0] if unit.evidence_points else unit.summary
        lines.append(f"- {unit.title} at {unit.organization}: {evidence}")
    return lines


def _template_matched_skills(
    job: JobListing,
    experience_units: list[ExperienceUnit],
) -> list[str]:
    candidate_skills = {
        skill.casefold(): skill
        for unit in experience_units
        for skill in unit.skills
    }
    matched: list[str] = []
    for requirement in [*job.requirements, *job.nice_to_have_skills]:
        key = requirement.casefold()
        if key in candidate_skills:
            matched.append(candidate_skills[key])
    return _dedupe(matched)


def _matched_skills_sentence(matched_skills: list[str]) -> str:
    if not matched_skills:
        return "No direct skill overlap was identified by the template fallback."
    return "Grounded skill overlap: " + ", ".join(matched_skills) + "."


def _job_context_sentence(job: JobListing) -> str:
    details = [
        value
        for value in (job.location, job.remote_policy, job.salary)
        if value
    ]
    if not details:
        return "No additional job context was available beyond the normalized listing."
    return "Job context: " + "; ".join(details) + "."


def _template_document_checklist(requirements: ApplicationRequirements | None) -> str:
    if requirements is None:
        return "No application requirements were available. Review the apply page manually."

    findings = [*requirements.required_documents, *requirements.upload_expectations]
    if not findings:
        return "No document upload requirements were identified. Review the apply page manually."

    lines = ["Document and upload checklist:"]
    for finding in findings:
        required = "required" if finding.required else "optional or preferred"
        lines.append(f"- {finding.label}: {required}. Evidence: {finding.evidence}")
        if finding.constraints:
            lines.append(f"  Constraints: {', '.join(finding.constraints)}")
    return "\n".join(lines)


def _template_form_answer(
    job: JobListing,
    selected_experience: list[ExperienceUnit],
    matched_skills: list[str],
) -> str:
    if selected_experience:
        evidence = selected_experience[0].evidence_points or [selected_experience[0].summary]
        return (
            f"My relevant experience includes {selected_experience[0].title}, "
            f"where I {evidence[0].rstrip('.').lower()}. "
            f"This is relevant to {job.title} at {job.company}. "
            f"{_matched_skills_sentence(matched_skills)}"
        )
    return (
        f"I am interested in the {job.title} role at {job.company}. "
        "Review this answer and add candidate-specific evidence before submission."
    )


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "artifact"


def _unique_id(value: str, seen_ids: set[str]) -> str:
    if value not in seen_ids:
        return value
    suffix = 2
    while f"{value}-{suffix}" in seen_ids:
        suffix += 1
    return f"{value}-{suffix}"


def _requirements_hint_at_cover_letter(
    job: JobListing,
    requirements: ApplicationRequirements,
) -> bool:
    haystack = " ".join(
        [
            job.description or "",
            *job.requirements,
            *requirements.source_evidence,
            *[item.label for item in requirements.required_documents],
        ]
    ).casefold()
    return any(term in haystack for term in ("cover letter", "motivation", "anschreiben"))


def _candidate_evidence_text(candidate_profile: CandidateProfile) -> str:
    profile_data = candidate_profile.candidate_profile
    extracted = profile_data.cv_extracted
    evidence_parts = [
        extracted.identity.full_name,
        extracted.identity.location,
        *extracted.work_experience,
        *extracted.education,
        *extracted.skills,
        *extracted.languages,
        *extracted.certifications,
        *extracted.projects,
        *extracted.references,
        *profile_data.candidate_preferences.target_roles,
    ]
    return " ".join(evidence_parts).casefold()


def _unsupported_requirement_terms(
    job: JobListing,
    candidate_evidence: str,
) -> list[str]:
    terms: list[str] = []
    for raw_term in [*job.requirements, *job.nice_to_have_skills]:
        term = _quality_term(raw_term)
        if not term:
            continue
        if term.casefold() not in candidate_evidence:
            terms.append(term)
    return _dedupe(terms)


def _quality_term(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" .,:;")
    if len(normalized) < 3:
        return ""
    if len(normalized.split()) > 4:
        return ""
    return normalized


def _sensitive_answer_findings(artifact: Any) -> list[str]:
    source_text = " ".join(
        str(value)
        for value in (
            artifact.label,
            artifact.source_prompt or "",
            artifact.source_requirement or "",
        )
        if value
    )
    if artifact.content.strip() and _is_sensitive_or_user_decision_field(source_text):
        return ["Generated answer for a sensitive or user-decision field."]
    return []


def _unsupported_claim_findings(
    content: str,
    unsupported_terms: list[str],
) -> list[str]:
    findings: list[str] = []
    for term in unsupported_terms:
        if _content_claims_experience_with_term(content, term):
            findings.append(f"Claims experience with unsupported requirement: {term}")
    return findings


def _content_claims_experience_with_term(content: str, term: str) -> bool:
    escaped_term = re.escape(term)
    claim_pattern = re.compile(
        rf"\b("
        rf"experience\s+(?:with|in)|"
        rf"experienced\s+(?:with|in)|"
        rf"skilled\s+(?:with|in)|"
        rf"proficient\s+(?:with|in)|"
        rf"expert\s+(?:with|in)"
        rf")\s+{escaped_term}\b",
        re.IGNORECASE,
    )
    return bool(claim_pattern.search(content))


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
        traces.extend(
            _finding_trace(kind, finding)
            for finding in findings
        )

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


def _is_sensitive_or_user_decision_field(value: str) -> bool:
    normalized = value.casefold()
    decision_terms = (
        "referral",
        "recommendation code",
        "empfehlung",
        "internal",
        "employee",
        "severe disability",
        "disability",
        "behinderung",
        "consent",
        "privacy",
        "datenschutz",
        "einwilligung",
    )
    return any(term in normalized for term in decision_terms)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _to_json(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    elif isinstance(value, list):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
    else:
        payload = value
    return json.dumps(payload, indent=2, ensure_ascii=True)
