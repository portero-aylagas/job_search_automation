"""Shared fill-plan review payload and submission helpers."""

from __future__ import annotations

from typing import TypedDict

from src.application_fill_plan import (
    apply_fill_plan_edits,
    fill_plan_blocked_field_edit_key,
    fill_plan_field_edit_key,
    fill_plan_needs_answer_edit_key,
    fill_plan_upload_edit_key,
)
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
)


class FillPlanReviewSubmission(TypedDict):
    """Editable fill-plan review maps accepted by the review service."""

    edited_values: dict[str, str]
    upload_paths_by_key: dict[str, str]
    needs_answer_values_by_key: dict[str, str]
    blocked_values_by_key: dict[str, str]


def build_fill_plan_review_payload(
    fill_plan: ApplicationFillPlan | None,
) -> dict[str, object] | None:
    """Return stable edit keys for the structured fill-plan review UI."""

    if fill_plan is None:
        return None
    required_rows: list[dict[str, object]] = []
    optional_rows: list[dict[str, object]] = []
    for kind, index, field in fill_plan_review_rows(fill_plan):
        row = fill_plan_row_payload(kind, index, field)
        if bool(row["required"]):
            required_rows.append(row)
        else:
            optional_rows.append(row)
    upload_rows = [
        {
            "edit_key": fill_plan_upload_edit_key(upload, index),
            "label": upload.label,
            "file_path": upload.file_path,
            "document_type": upload.document_type,
            "required": upload.required,
            "source": upload.source,
            "confidence": upload.confidence,
        }
        for index, upload in enumerate(fill_plan.upload_files)
    ]
    return {
        "required_rows": required_rows,
        "optional_rows": optional_rows,
        "upload_rows": upload_rows,
    }


def fill_plan_review_rows(
    fill_plan: ApplicationFillPlan,
) -> list[
    tuple[
        str,
        int,
        ApplicationFillFieldValue
        | ApplicationFillNeedsAnswerField
        | ApplicationFillBlockedField,
    ]
]:
    """Return fill-plan rows in the same grouping order as the review UI."""

    return [
        *[
            ("field", index, field)
            for index, field in enumerate(fill_plan.field_values)
        ],
        *[
            ("needs", index, field)
            for index, field in enumerate(fill_plan.needs_answer_fields)
        ],
        *[
            ("blocked", index, field)
            for index, field in enumerate(fill_plan.blocked_fields)
        ],
    ]


def fill_plan_row_payload(
    kind: str,
    index: int,
    field: ApplicationFillFieldValue
    | ApplicationFillNeedsAnswerField
    | ApplicationFillBlockedField,
) -> dict[str, object]:
    """Return one fill-plan row with the backend edit key and default value."""

    if kind == "field":
        edit_key = fill_plan_field_edit_key(field, index)  # type: ignore[arg-type]
        value = field.value  # type: ignore[union-attr]
    elif kind == "needs":
        edit_key = fill_plan_needs_answer_edit_key(field, index)  # type: ignore[arg-type]
        value = ""
    else:
        edit_key = fill_plan_blocked_field_edit_key(field, index)  # type: ignore[arg-type]
        value = "true" if field.input_type.casefold() == "checkbox" and field.required else ""
    return {
        "kind": kind,
        "edit_key": edit_key,
        "label": field.label,
        "value": value,
        "required": field.required,
        "input_type": field.input_type,
        "options": list(field.options),
        "reason": getattr(field, "reason", ""),
        "source": field.source,
        "confidence": field.confidence,
    }


def build_fill_plan_review_submission_from_defaults(
    fill_plan: ApplicationFillPlan,
) -> FillPlanReviewSubmission:
    """Return the review maps produced by saving the current UI defaults."""

    submission: FillPlanReviewSubmission = {
        "edited_values": {},
        "upload_paths_by_key": {},
        "needs_answer_values_by_key": {},
        "blocked_values_by_key": {},
    }
    for kind, index, field in fill_plan_review_rows(fill_plan):
        row = fill_plan_row_payload(kind, index, field)
        edit_key = str(row["edit_key"])
        value = str(row["value"] or "")
        if kind == "field":
            submission["edited_values"][edit_key] = value
        elif kind == "needs":
            submission["needs_answer_values_by_key"][edit_key] = value
        elif kind == "blocked":
            submission["blocked_values_by_key"][edit_key] = value

    for index, upload in enumerate(fill_plan.upload_files):
        submission["upload_paths_by_key"][
            fill_plan_upload_edit_key(upload, index)
        ] = upload.file_path

    return submission


def apply_fill_plan_review_submission(
    fill_plan: ApplicationFillPlan,
    submission: FillPlanReviewSubmission,
) -> ApplicationFillPlan:
    """Apply one fill-plan review submission to a draft fill plan."""

    return apply_fill_plan_edits(
        fill_plan,
        submission["edited_values"],
        upload_paths_by_key=submission["upload_paths_by_key"],
        needs_answer_values_by_key=submission["needs_answer_values_by_key"],
        blocked_values_by_key=submission["blocked_values_by_key"],
    )
