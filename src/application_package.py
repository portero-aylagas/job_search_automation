"""Application package generation, review recovery, export, and persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from src import llm_client
from src.application_package_markdown import render_application_package_markdown
from src.application_package_quality import (
    apply_application_package_quality_checks,
    is_sensitive_or_user_decision_field,
)
from src.application_package_storage import (
    APPLICATION_PACKAGE_MARKDOWN_FILENAME,
    export_cover_letter_artifact,
    load_application_package,
    save_application_package,
    update_tracker_for_application_package,
)
from src.application_package_traceability import attach_application_package_traceability
from src.prompt_templates import get_prompt, get_prompt_template_metadata
from src.schemas import (
    AIWorkflowTrace,
    ApplicationPackage,
    ApplicationRequirements,
    CandidateProfile,
    ExperienceUnit,
    JobListing,
)

__all__ = [
    "APPLICATION_PACKAGE_MARKDOWN_FILENAME",
    "export_cover_letter_artifact",
    "load_application_package",
    "render_application_package_markdown",
    "save_application_package",
    "update_tracker_for_application_package",
]

PackageGenerator = Callable[
    [CandidateProfile, list[ExperienceUnit], JobListing, ApplicationRequirements | None],
    ApplicationPackage,
]


class ApplicationArtifactManifestItem(BaseModel):
    """Artifact request included in the package-generation manifest."""

    id: str
    type: str
    label: str
    required: bool = False
    source_prompt: str | None = None
    source_requirement: str | None = None


class LLMApplicationArtifact(BaseModel):
    """LLM-safe generated artifact before local package normalization."""

    id: str
    type: str
    label: str
    required: bool = False
    status: Literal["draft", "needs_review"] = "draft"
    content: str = ""
    source_prompt: str | None = None
    source_requirement: str | None = None


class LLMApplicationPackageResponse(BaseModel):
    """LLM-safe application package response before local normalization."""

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
    """Generate, trace, quality-check, and normalize an application package."""

    selected_generator = generator or generate_application_package_with_llm
    package = selected_generator(candidate_profile, experience_units, job, requirements)
    package = attach_application_package_traceability(package, requirements, experience_units)
    package = apply_application_package_quality_checks(
        package,
        candidate_profile,
        job,
    )
    return normalize_application_package(job, package)


def build_application_artifact_manifest(
    job: JobListing,
    requirements: ApplicationRequirements | None = None,
) -> list[ApplicationArtifactManifestItem]:
    """Build the required artifact manifest from job and application requirements."""

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
        if is_sensitive_or_user_decision_field(question.question):
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
        if is_sensitive_or_user_decision_field(field.label):
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
    """Return reviewer-facing missing-information defaults for package generation."""

    missing: list[str] = []
    profile_data = candidate_profile.candidate_profile
    identity = profile_data.cv_extracted.identity

    if not identity.first_name.strip():
        missing.append("Candidate first name is missing.")
    if not identity.last_name.strip():
        missing.append("Candidate surname is missing.")
    if not identity.email.strip():
        missing.append("Candidate email is missing.")
    if not identity.phone.strip():
        missing.append("Candidate phone is missing.")
    if identity.gender is None:
        missing.append("Candidate gender is missing.")
    if not identity.street_address.strip():
        missing.append("Candidate street is missing.")
    if not identity.street_number.strip():
        missing.append("Candidate street number is missing.")
    if not identity.city.strip():
        missing.append("Candidate city is missing.")
    if not identity.postal_code.strip():
        missing.append("Candidate postal code is missing.")
    if not identity.country.strip():
        missing.append("Candidate country of residence is missing.")
    if not identity.nationality.strip():
        missing.append("Candidate nationality is missing.")
    if not profile_data.source_documents.cv.file_path.strip():
        missing.append("Candidate CV file is missing.")

    if requirements is None:
        missing.append("Application requirements have not been discovered for this job.")
        return missing

    for question in requirements.screening_questions:
        if is_sensitive_or_user_decision_field(question.question):
            missing.append(f"User decision required: {question.question}")

    for field in [*requirements.custom_form_fields, *requirements.profile_fields]:
        label = field.label or field.name
        if is_sensitive_or_user_decision_field(label):
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
    """Generate an application package with the configured live LLM profile."""

    manifest = build_application_artifact_manifest(job, requirements)
    missing_defaults = build_missing_information_defaults(candidate_profile, requirements)
    requirements_json = _to_json(requirements) if requirements else "Not discovered."
    workflow_trace: AIWorkflowTrace | None = None
    prompt_metadata = get_prompt_template_metadata(
        "application_package",
        "generate_package",
    )

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
        **prompt_metadata,
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


def normalize_application_package(
    job: JobListing,
    package: ApplicationPackage,
) -> ApplicationPackage:
    """Normalize package IDs, status fields, and duplicate list values."""

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
    """Return a package copy with reviewer edits applied to matching artifacts."""

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
    """Return a rejected package copy with the reviewer reason recorded."""

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


def slugify(value: str) -> str:
    """Return a lowercase slug suitable for generated artifact IDs."""

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
