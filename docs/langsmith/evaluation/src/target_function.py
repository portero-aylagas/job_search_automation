"""LangSmith target function for CV and supplemental document extraction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.candidate_profile import merge_supplemental_extracted_data
from src.cv_extraction import (
    CVDataExtractor,
    CVDocumentInspector,
    SupplementalDataExtractor,
    run_cv_extraction_task,
    run_optional_document_extraction_task,
)
from src.schemas import CandidateCVExtracted, CandidateSupplementalExtracted

PROJECT_ROOT = Path(__file__).resolve().parents[4]


try:
    from langsmith import traceable
except ImportError:

    def traceable(func: Callable[..., Any]) -> Callable[..., Any]:
        """Return the function unchanged when LangSmith is unavailable."""

        return func


def resolve_project_path(path_value: str | Path) -> Path:
    """Return an absolute path for a repository-relative evaluation fixture path."""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


@traceable
def target_function(inputs: dict[str, Any]) -> dict[str, Any]:
    """Extract candidate evidence for one LangSmith dataset example.

    Args:
        inputs: Dataset input containing `case_id`, `cv_path`,
            `optional_document_paths`, and `document_types`.

    Returns:
        A `CandidateCVExtracted` JSON dictionary.
    """

    return run_target_function(inputs)


def run_target_function(
    inputs: dict[str, Any],
    *,
    cv_extractor: CVDataExtractor | None = None,
    supplemental_extractor: SupplementalDataExtractor | None = None,
    inspector: CVDocumentInspector | None = None,
) -> dict[str, Any]:
    """Run the target function with injectable extractors for local tests."""

    cv_path = resolve_project_path(str(inputs["cv_path"]))
    extracted = run_cv_extraction_task(
        cv_path,
        inspector=inspector,
        extractor=cv_extractor,
    )
    merged = extracted.model_copy(deep=True)

    for document_path in inputs.get("optional_document_paths", []):
        supplemental = run_optional_document_extraction_task(
            resolve_project_path(str(document_path)),
            inspector=inspector,
            extractor=supplemental_extractor,
        )
        merge_supplemental_extracted_data(merged, supplemental)

    return merged.model_dump(mode="json")


def run_local_smoke_check(
    examples: list[dict[str, Any]],
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Run a small local target check over the first examples."""

    return [target_function(example["inputs"]) for example in examples[:limit]]


def empty_supplemental_extractor(_: object) -> CandidateSupplementalExtracted:
    """Return an empty supplemental extraction for simple local smoke tests."""

    return CandidateSupplementalExtracted()


def empty_cv_extractor(_: object) -> CandidateCVExtracted:
    """Return an empty CV extraction for simple local smoke tests."""

    return CandidateCVExtracted()
