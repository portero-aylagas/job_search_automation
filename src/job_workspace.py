"""Backend helpers for saved jobs, requirements, packages, and apply flow."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.application_fill_plan import (
    get_application_fill_plan_freshness_blockers,
    get_application_fill_plan_review_blockers,
)
from src.application_package import apply_manual_artifact_edits
from src.schemas import (
    AIWorkflowTrace,
    ApplicationArtifact,
    ApplicationFillPlan,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    CandidateProfile,
    JobListing,
)


def build_review_checklist(
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
) -> list[str]:
    """Build a de-duplicated list of human decisions still worth surfacing."""

    items: list[str] = []
    if requirements is not None:
        items.extend(requirement_review_labels(requirements))
    if package is not None:
        items.extend(package.missing_information)
    return [
        item
        for item in deduplicate_review_items(items)
        if not review_item_is_represented_in_fill_plan(item, fill_plan)
    ]


def review_item_is_represented_in_fill_plan(
    item: str,
    fill_plan: ApplicationFillPlan | None,
) -> bool:
    """Return whether a review item already appears as an editable fill-plan field."""

    if fill_plan is None:
        return False
    normalized_item = normalize_review_item(item)
    editable_labels = [
        field.label
        for field in [
            *fill_plan.field_values,
            *fill_plan.needs_answer_fields,
            *fill_plan.blocked_fields,
        ]
    ]
    return normalized_item in {
        normalize_review_item(label) for label in editable_labels if label.strip()
    }


def requirement_review_labels(requirements: ApplicationRequirements) -> list[str]:
    """Return concise labels for requirement groups that require human awareness."""

    labels: list[str] = []
    labels.extend(finding.label for finding in requirements.consent_requirements)
    labels.extend(question.question for question in requirements.screening_questions)
    labels.extend(field.label for field in requirements.custom_form_fields)
    labels.extend(requirements.missing_or_uncertain)
    return labels


def deduplicate_review_items(items: list[str]) -> list[str]:
    """Return review items without repeated labels across workflow artifacts."""

    seen: set[str] = set()
    deduplicated: list[str] = []
    for item in items:
        normalized_item = normalize_review_item(item)
        if not normalized_item or normalized_item in seen:
            continue
        seen.add(normalized_item)
        deduplicated.append(clean_review_item_label(item))
    return deduplicated


def normalize_review_item(item: str) -> str:
    """Normalize semantically repeated review labels for de-duplication."""

    normalized = clean_review_item_label(item).casefold()
    replacements = {
        "user decision required: ": "",
        "user must review consent requirement: ": "",
        "optional consent for ": "",
        "privacy policy acknowledgement": "privacy policy acknowledgment",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    if "schwerbehinderung" in normalized or "behinderung" in normalized:
        return "disability disclosure"
    if (
        "empfehlung" in normalized
        or "referral" in normalized
        or "recommendation code" in normalized
    ):
        return "employee referral"
    if "datenschutz" in normalized or "privacy policy" in normalized:
        return "privacy consent"
    if "firmengruppe" in normalized or "group companies" in normalized:
        return "group company data sharing"
    if "intern" in normalized or "internal" in normalized:
        return "internal application"
    if "zeugnisse" in normalized or "certificates" in normalized:
        return "certificates upload"
    if "deadline" in normalized or "application deadline" in normalized:
        return "application deadline"
    if "contact" in normalized or "recruiter" in normalized:
        return "fallback contact"
    return normalized


def clean_review_item_label(item: str) -> str:
    """Trim noisy prefixes from review items while preserving meaning."""

    cleaned = item.strip()
    prefixes = [
        "User decision required: ",
        "User must review consent requirement: ",
        "User should confirm ",
    ]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            return cleaned.removeprefix(prefix).strip()
    return cleaned


def get_job_extraction_trace(job: JobListing) -> AIWorkflowTrace | None:
    """Return the stored job extraction trace as workflow metadata when valid."""

    raw_trace = job.job_details.get("job_extraction_trace")
    if raw_trace is None:
        return None
    try:
        return AIWorkflowTrace.model_validate(raw_trace)
    except ValueError:
        return None


def get_fill_plan_generation_blockers(
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
) -> list[str]:
    """Return blockers that prevent generating an application fill plan."""

    blockers: list[str] = []
    if requirements is None:
        blockers.append("Discover application requirements.")
    elif requirements.status != "discovered" or not requirements.job_preserving:
        blockers.append("Resolve reviewed application requirements.")
    elif requirements.review_status != "reviewed":
        blockers.append("Review the discovered application requirements.")

    if package is None:
        blockers.append("Generate the application package.")
    elif package.status == "rejected":
        blockers.append("Regenerate or manually edit the rejected application package.")
    elif package.status != "approved":
        blockers.append("Save the application package review.")

    return blockers


def build_package_review_saved_message(
    json_path: Path,
    markdown_path: Path,
    package: ApplicationPackage,
) -> str:
    """Return a save confirmation that names package exports and locations."""

    lines = [
        "Package review changes saved.",
        f"- Package JSON: {json_path}",
        f"- Markdown export: {markdown_path}",
    ]
    cover_letter = find_cover_letter_artifact(package)
    if cover_letter is not None:
        generated_path = str(cover_letter.metadata.get("generated_file_path") or "").strip()
        if generated_path:
            lines.append(f"- Cover letter PDF artifact: {generated_path}")
    return "\n".join(lines)


def find_cover_letter_artifact(package: ApplicationPackage) -> ApplicationArtifact | None:
    """Return the first cover-letter artifact in a package."""

    for artifact in package.artifacts:
        if is_cover_letter_artifact(artifact):
            return artifact
    return None


def build_application_package_summary(
    package: ApplicationPackage,
) -> dict[str, str | int | list[str]]:
    """Return compact package metadata for the package review form."""

    return {
        "status": package.status,
        "artifact_count": len(package.artifacts),
        "missing_information": list(package.missing_information),
        "selected_experience_units": list(package.selected_experience_units),
        "generation_notes": list(package.generation_notes),
    }


def build_application_artifact_review_metadata(
    artifact: ApplicationArtifact,
) -> list[str]:
    """Return reviewer-facing metadata labels for an application artifact."""

    metadata = []
    if artifact.source_prompt:
        metadata.append(f"Source prompt: {artifact.source_prompt}")
    if artifact.source_requirement:
        metadata.append(f"Source requirement: {artifact.source_requirement}")
    return metadata


def application_artifact_review_key(job_id: str, artifact: ApplicationArtifact) -> str:
    """Return a stable widget key tied to the current artifact content."""

    content_hash = hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()[:12]
    return f"application_package_review_{job_id}_{artifact.id}_{content_hash}"


def order_application_package_artifacts_for_review(
    artifacts: list[ApplicationArtifact],
) -> list[ApplicationArtifact]:
    """Return artifacts with the cover letter first while preserving other order."""

    return sorted(
        artifacts,
        key=lambda artifact: 0 if is_cover_letter_artifact(artifact) else 1,
    )


def is_cover_letter_artifact(artifact: ApplicationArtifact) -> bool:
    """Return whether an artifact is the cover-letter draft."""

    normalized_label = artifact.label.casefold()
    return artifact.type == "cover_letter" or "cover letter" in normalized_label


def application_package_review_has_content_changes(
    package: ApplicationPackage,
    edits_by_artifact_id: dict[str, str],
) -> bool:
    """Return whether reviewer edits change any stored artifact content."""

    for artifact in package.artifacts:
        if artifact.id not in edits_by_artifact_id:
            continue
        if str(edits_by_artifact_id[artifact.id]).strip() != artifact.content:
            return True
    return False


def apply_application_package_review_edits(
    package: ApplicationPackage,
    edits_by_artifact_id: dict[str, str],
) -> ApplicationPackage:
    """Apply reviewer edits and unlock legacy rejected packages when changed."""

    edited_package = apply_manual_artifact_edits(package, edits_by_artifact_id)
    if (
        package.status == "rejected"
        and application_package_review_has_content_changes(package, edits_by_artifact_id)
    ):
        edited_package.status = "manually_edited"
    return edited_package


def mark_application_package_reviewed(package: ApplicationPackage) -> ApplicationPackage:
    """Return a package marked as reviewed by the user."""

    reviewed_package = package.model_copy(deep=True)
    reviewed_package.status = "approved"
    for artifact in reviewed_package.artifacts:
        artifact.status = "approved"
    return reviewed_package


def apply_application_requirements_review_edits(
    requirements: ApplicationRequirements,
    *,
    job_preserving: bool,
    confidence: str,
    blocked_reason: str,
    required_documents_text: str,
    upload_expectations_text: str,
    motivation_label: str,
    motivation_required: bool,
    profile_fields_text: str,
    screening_questions_text: str,
    custom_form_fields_text: str,
    consent_requirements_text: str,
    privacy_login_ats_gates_text: str,
    deadlines_text: str,
    contact_or_fallback_text: str,
    missing_or_uncertain_text: str,
) -> ApplicationRequirements:
    """Apply editable requirement review fields to a requirements object."""

    edited = requirements.model_copy(deep=True)
    edited.job_preserving = job_preserving
    edited.status = "discovered" if job_preserving else "blocked"
    edited.review_status = "reviewed" if job_preserving else "draft"
    edited.confidence = confidence  # type: ignore[assignment]
    edited.blocked_reason = blocked_reason.strip() or None
    edited.required_documents = parse_requirement_findings_from_edit(
        required_documents_text,
        requirements.required_documents,
    )
    edited.upload_expectations = parse_requirement_findings_from_edit(
        upload_expectations_text,
        requirements.upload_expectations,
    )
    edited.profile_fields = parse_application_form_fields_from_edit(
        profile_fields_text,
        requirements.profile_fields,
    )
    edited.screening_questions = parse_screening_questions_from_edit(
        screening_questions_text,
        requirements.screening_questions,
    )
    edited.custom_form_fields = parse_application_form_fields_from_edit(
        custom_form_fields_text,
        requirements.custom_form_fields,
    )
    edited.motivation_letter = build_motivation_requirement(
        motivation_label,
        motivation_required,
        requirements.motivation_letter,
    )
    edited.consent_requirements = parse_requirement_findings_from_edit(
        consent_requirements_text,
        requirements.consent_requirements,
    )
    edited.privacy_login_ats_gates = parse_requirement_findings_from_edit(
        privacy_login_ats_gates_text,
        requirements.privacy_login_ats_gates,
    )
    edited.deadlines = parse_requirement_findings_from_edit(
        deadlines_text,
        requirements.deadlines,
    )
    edited.contact_or_fallback = parse_requirement_findings_from_edit(
        contact_or_fallback_text,
        requirements.contact_or_fallback,
    )
    edited.missing_or_uncertain = lines_from_requirement_edit(missing_or_uncertain_text)
    return ApplicationRequirements.model_validate(edited.model_dump(mode="json"))


def lines_from_requirement_edit(value: str) -> list[str]:
    """Parse editable bullet lines."""

    return [line.strip("-*• \t") for line in value.splitlines() if line.strip("-*• \t")]


def parse_requirement_findings_from_edit(
    value: str,
    existing_findings: list[ApplicationRequirementFinding],
) -> list[ApplicationRequirementFinding]:
    """Parse editable requirement finding lines while preserving existing metadata."""

    findings: list[ApplicationRequirementFinding] = []
    for index, line in enumerate(lines_from_requirement_edit(value)):
        label, required = parse_required_prefix(line)
        if not label:
            continue
        existing = existing_findings[index] if index < len(existing_findings) else None
        findings.append(
            ApplicationRequirementFinding(
                label=label,
                required=required if required is not None else bool(existing and existing.required),
                evidence=existing.evidence if existing else "",
                confidence=existing.confidence if existing else "medium",
                constraints=list(existing.constraints) if existing else [],
            )
        )
    return findings


def parse_screening_questions_from_edit(
    value: str,
    existing_questions: list[ApplicationScreeningQuestion],
) -> list[ApplicationScreeningQuestion]:
    """Parse editable screening question lines."""

    questions: list[ApplicationScreeningQuestion] = []
    for index, line in enumerate(lines_from_requirement_edit(value)):
        question_text, input_type = split_edit_line(line)
        question, required = parse_required_prefix(question_text)
        if not question:
            continue
        existing = existing_questions[index] if index < len(existing_questions) else None
        questions.append(
            ApplicationScreeningQuestion(
                question=question,
                required=required if required is not None else bool(existing and existing.required),
                input_type=input_type or (existing.input_type if existing else ""),
                evidence=existing.evidence if existing else "",
                confidence=existing.confidence if existing else "medium",
            )
        )
    return questions


def parse_application_form_fields_from_edit(
    value: str,
    existing_fields: list[ApplicationFormField],
) -> list[ApplicationFormField]:
    """Parse editable application form field lines."""

    fields: list[ApplicationFormField] = []
    for index, line in enumerate(lines_from_requirement_edit(value)):
        label_text, input_type, options_text = split_form_field_edit_line(line)
        label, required = parse_required_prefix(label_text)
        if not label:
            continue
        existing = existing_fields[index] if index < len(existing_fields) else None
        fields.append(
            ApplicationFormField(
                name=existing.name if existing else "",
                label=label,
                required=required if required is not None else bool(existing and existing.required),
                input_type=input_type or (existing.input_type if existing else ""),
                options=parse_options(options_text)
                if options_text
                else (list(existing.options) if existing else []),
                evidence=existing.evidence if existing else "",
                confidence=existing.confidence if existing else "medium",
            )
        )
    return fields


def build_motivation_requirement(
    label: str,
    required: bool,
    existing: ApplicationRequirementFinding | None,
) -> ApplicationRequirementFinding | None:
    """Return an edited motivation requirement when one is present."""

    clean_label = label.strip()
    if not clean_label:
        return None
    return ApplicationRequirementFinding(
        label=clean_label,
        required=required,
        evidence=existing.evidence if existing else "",
        confidence=existing.confidence if existing else "medium",
        constraints=list(existing.constraints) if existing else [],
    )


def parse_required_prefix(line: str) -> tuple[str, bool | None]:
    """Parse an optional [required] or [optional] marker from an edit line."""

    clean_line = line.strip()
    lowered = clean_line.casefold()
    if lowered.startswith("[required]"):
        return clean_line[len("[required]") :].strip(), True
    if lowered.startswith("[optional]"):
        return clean_line[len("[optional]") :].strip(), False
    return clean_line, None


def split_edit_line(line: str) -> tuple[str, str]:
    """Split a simple editable row into label and type."""

    parts = [part.strip() for part in line.split("|", maxsplit=1)]
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def split_form_field_edit_line(line: str) -> tuple[str, str, str]:
    """Split a form-field edit row into label, input type, and options text."""

    parts = [part.strip() for part in line.split("|", maxsplit=2)]
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], parts[2]


def parse_options(value: str) -> list[str]:
    """Parse semicolon or comma separated option labels."""

    separator = ";" if ";" in value else ","
    return [option.strip() for option in value.split(separator) if option.strip()]


def get_apply_assistance_blockers(
    job: JobListing,
    requirements: ApplicationRequirements | None,
    package: ApplicationPackage | None,
    fill_plan: ApplicationFillPlan | None,
    *,
    candidate_profile: CandidateProfile | None = None,
) -> list[str]:
    """Return blockers that prevent opening the apply page from the Jobs workspace."""

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
        fill_plan_review_blockers = get_application_fill_plan_review_blockers(fill_plan)
        if fill_plan_review_blockers:
            blockers.extend(fill_plan_review_blockers)
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
