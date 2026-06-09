"""Evaluators for CV extraction LangSmith experiments."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.schemas import CandidateCVExtracted

REFERENCE_FIELDS = (
    "work_experience",
    "education",
    "skills",
    "languages",
    "certifications",
    "projects",
    "references",
)

JUDGE_MODEL = os.getenv("CV_EVAL_LLM_JUDGE_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4"))

IDENTITY_FIELDS = (
    "full_name",
    "first_name",
    "last_name",
    "gender",
    "email",
    "phone",
    "city",
    "country",
    "nationality",
)


def correctness_evaluator(
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Score extraction correctness against the reference output.

    The score combines identity exact-match coverage with list-field evidence
    coverage. It is deterministic so it can run in CI without model credentials.
    """

    del inputs
    identity_score = _identity_score(
        outputs.get("identity", {}),
        reference_outputs.get("identity", {}),
    )
    list_score = _list_fields_score(outputs, reference_outputs, REFERENCE_FIELDS)
    score = round((identity_score + list_score) / 2, 4)
    return {
        "key": "cv_extraction_correctness",
        "score": score,
        "comment": (
            f"identity={identity_score:.2f}; evidence_fields={list_score:.2f}; "
            f"score={score:.2f}"
        ),
    }


def evidence_completeness_evaluator(
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Score whether optional-document evidence was preserved in the output."""

    document_types = set(inputs.get("document_types", []))
    expected_fields = ["certifications", "references"]
    if "recommendation_letter" not in document_types:
        expected_fields.remove("references")
    if "certificate" not in document_types:
        expected_fields.remove("certifications")
    if not expected_fields:
        expected_fields = list(REFERENCE_FIELDS)

    score = _list_fields_score(outputs, reference_outputs, tuple(expected_fields))
    return {
        "key": "supplemental_evidence_completeness",
        "score": round(score, 4),
        "comment": f"checked_fields={','.join(expected_fields)}; score={score:.2f}",
    }


def schema_validation_evaluator(
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Score whether the output is valid `CandidateCVExtracted` JSON."""

    del inputs, reference_outputs
    try:
        CandidateCVExtracted.model_validate(outputs)
    except ValidationError as exc:
        errors = "; ".join(
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()[:5]
        )
        return {
            "key": "cv_schema_validity",
            "score": 0.0,
            "comment": f"schema validation failed: {errors}",
        }
    return {
        "key": "cv_schema_validity",
        "score": 1.0,
        "comment": "output validates as CandidateCVExtracted",
    }


def grounding_evaluator(
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Score whether output claims are covered by the reference fixture."""

    del inputs
    claims = _claim_values(outputs)
    if not claims:
        return {
            "key": "reference_grounding",
            "score": 1.0,
            "comment": "no non-empty output claims to check",
        }
    reference_values = _claim_values(reference_outputs)
    unsupported = [
        claim
        for claim in claims
        if not _contains_normalized_value(claim, reference_values)
    ]
    score = round((len(claims) - len(unsupported)) / len(claims), 4)
    return {
        "key": "reference_grounding",
        "score": score,
        "comment": (
            f"claims={len(claims)}; unsupported={len(unsupported)}; "
            f"examples={_preview_values(unsupported)}"
        ),
    }


def llm_judge_evaluator(
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Optional LLM-as-judge evaluator for live LangSmith experiments.

    The evaluator is intentionally disabled unless `CV_EVAL_ENABLE_LLM_JUDGE`
    is true. CI and local imports can call it safely without credentials.
    """

    del inputs
    if not _env_flag("CV_EVAL_ENABLE_LLM_JUDGE"):
        return {
            "key": "llm_reference_judge",
            "score": None,
            "comment": "skipped; set CV_EVAL_ENABLE_LLM_JUDGE=true for live runs",
        }
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "key": "llm_reference_judge",
            "score": None,
            "comment": "skipped; OPENAI_API_KEY is not set",
        }

    try:
        result = _run_llm_judge(outputs=outputs, reference_outputs=reference_outputs)
    except Exception as exc:
        return {
            "key": "llm_reference_judge",
            "score": None,
            "comment": f"judge failed: {exc}",
        }
    return {
        "key": "llm_reference_judge",
        "score": round(result.score, 4),
        "comment": result.comment,
    }


def evaluation_suite(*, include_llm_judge: bool | None = None) -> list[Any]:
    """Return the evaluator list for LangSmith runs."""

    evaluators: list[Any] = [
        correctness_evaluator,
        evidence_completeness_evaluator,
        schema_validation_evaluator,
        grounding_evaluator,
    ]
    if include_llm_judge is None:
        include_llm_judge = _env_flag("CV_EVAL_ENABLE_LLM_JUDGE")
    if include_llm_judge:
        evaluators.append(llm_judge_evaluator)
    return evaluators


class _JudgeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    comment: str


def _run_llm_judge(
    *,
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> _JudgeResult:
    from openai import OpenAI

    client = OpenAI(max_retries=0)
    response = client.responses.parse(
        model=JUDGE_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You are evaluating structured CV extraction. Score 1.0 only "
                    "when the candidate identity and evidence are faithful to the "
                    "reference. Penalize missing evidence and unsupported claims."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"output": outputs, "reference": reference_outputs},
                    ensure_ascii=True,
                ),
            },
        ],
        text_format=_JudgeResult,
        temperature=0.0,
        max_output_tokens=500,
    )
    if response.output_parsed is None:
        raise RuntimeError("judge returned no parsed output")
    return response.output_parsed


def _identity_score(outputs: dict[str, Any], reference: dict[str, Any]) -> float:
    expected_items = [
        (field, _normalize_scalar(reference.get(field)))
        for field in IDENTITY_FIELDS
        if _normalize_scalar(reference.get(field))
    ]
    if not expected_items:
        return 1.0
    matched = 0
    for field, expected_value in expected_items:
        if _normalize_scalar(outputs.get(field)) == expected_value:
            matched += 1
    return matched / len(expected_items)


def _list_fields_score(
    outputs: dict[str, Any],
    reference: dict[str, Any],
    fields: Iterable[str],
) -> float:
    expected_count = 0
    matched_count = 0
    for field in fields:
        expected_values = [_normalize_scalar(item) for item in reference.get(field, [])]
        expected_values = [item for item in expected_values if item]
        output_values = [_normalize_scalar(item) for item in outputs.get(field, [])]
        expected_count += len(expected_values)
        matched_count += sum(
            1
            for expected_value in expected_values
            if _contains_normalized_value(expected_value, output_values)
        )
    if expected_count == 0:
        return 1.0
    return matched_count / expected_count


def _contains_normalized_value(expected_value: str, output_values: list[str]) -> bool:
    return any(
        expected_value == output_value
        or expected_value in output_value
        or output_value in expected_value
        for output_value in output_values
    )


def _claim_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    identity = payload.get("identity", {})
    if isinstance(identity, dict):
        values.extend(
            _normalize_scalar(identity.get(field))
            for field in IDENTITY_FIELDS
            if _normalize_scalar(identity.get(field))
        )
    for field in REFERENCE_FIELDS:
        field_values = payload.get(field, [])
        if isinstance(field_values, list):
            values.extend(
                _normalize_scalar(value)
                for value in field_values
                if _normalize_scalar(value)
            )
    return values


def _preview_values(values: list[str], *, limit: int = 3) -> str:
    if not values:
        return "none"
    return " | ".join(values[:limit])


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _normalize_scalar(value: object) -> str:
    return " ".join(str(value or "").casefold().split())
