"""Inline code bodies for LangSmith platform code evaluators."""

from __future__ import annotations


def correctness_code() -> str:
    """Return the LangSmith inline code for extraction correctness."""

    return _common_code_helpers() + r'''
def perform_eval(run, example):
    outputs = _outputs(run)
    reference = _reference(example)
    expected_items = [
        (field, _normalize_scalar(reference.get("identity", {}).get(field)))
        for field in IDENTITY_FIELDS
        if _normalize_scalar(reference.get("identity", {}).get(field))
    ]
    if expected_items:
        matched = sum(
            1
            for field, expected_value in expected_items
            if _normalize_scalar(outputs.get("identity", {}).get(field)) == expected_value
        )
        identity_score = matched / len(expected_items)
    else:
        identity_score = 1.0
    list_score = _list_fields_score(outputs, reference, REFERENCE_FIELDS)
    score = round((identity_score + list_score) / 2, 4)
    return {
        "cv_extraction_correctness": {
            "score": score,
            "comment": (
                f"identity={identity_score:.2f}; evidence_fields={list_score:.2f}; "
                f"score={score:.2f}"
            ),
        }
    }
'''


def supplemental_evidence_code() -> str:
    """Return the LangSmith inline code for supplemental evidence scoring."""

    return _common_code_helpers() + r'''
def perform_eval(run, example):
    inputs = _inputs(example)
    outputs = _outputs(run)
    reference = _reference(example)
    document_types = set(inputs.get("document_types", []))
    expected_fields = ["certifications", "references"]
    if "recommendation_letter" not in document_types:
        expected_fields.remove("references")
    if "certificate" not in document_types:
        expected_fields.remove("certifications")
    if not expected_fields:
        expected_fields = list(REFERENCE_FIELDS)
    score = _list_fields_score(outputs, reference, tuple(expected_fields))
    return {
        "supplemental_evidence_completeness": {
            "score": round(score, 4),
            "comment": f"checked_fields={','.join(expected_fields)}; score={score:.2f}",
        }
    }
'''


def schema_validity_code() -> str:
    """Return the LangSmith inline code for CV schema shape validation."""

    return r'''
LIST_FIELDS = (
    "work_experience",
    "education",
    "skills",
    "languages",
    "certifications",
    "projects",
    "references",
)


def perform_eval(run, example):
    del example
    outputs = run.get("outputs", {})
    errors = []
    if not isinstance(outputs, dict):
        errors.append("outputs")
    else:
        identity = outputs.get("identity")
        if not isinstance(identity, dict):
            errors.append("identity")
        for field in LIST_FIELDS:
            value = outputs.get(field, [])
            if value is not None and not isinstance(value, list):
                errors.append(field)
    if errors:
        return {
            "cv_schema_validity": {
                "score": 0.0,
                "comment": "schema validation failed: " + ", ".join(errors[:5]),
            }
        }
    return {
        "cv_schema_validity": {
            "score": 1.0,
            "comment": "output has CandidateCVExtracted-compatible shape",
        }
    }
'''


def reference_grounding_code() -> str:
    """Return the LangSmith inline code for reference grounding."""

    return _common_code_helpers() + r'''
def perform_eval(run, example):
    outputs = _outputs(run)
    reference = _reference(example)
    claims = _claim_values(outputs)
    if not claims:
        return {
            "reference_grounding": {
                "score": 1.0,
                "comment": "no non-empty output claims to check",
            }
        }
    reference_values = _claim_values(reference)
    unsupported = [
        claim
        for claim in claims
        if not _contains_normalized_value(claim, reference_values)
    ]
    score = round((len(claims) - len(unsupported)) / len(claims), 4)
    return {
        "reference_grounding": {
            "score": score,
            "comment": (
                f"claims={len(claims)}; unsupported={len(unsupported)}; "
                f"examples={_preview_values(unsupported)}"
            ),
        }
    }
'''


def _common_code_helpers() -> str:
    return r'''
REFERENCE_FIELDS = (
    "work_experience",
    "education",
    "skills",
    "languages",
    "certifications",
    "projects",
    "references",
)
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


def _payload(value):
    if isinstance(value, dict):
        return value
    return {}


def _outputs(run):
    return _payload(run.get("outputs", {}))


def _reference(example):
    return _payload(example.get("outputs", {}))


def _inputs(example):
    return _payload(example.get("inputs", {}))


def _normalize_scalar(value):
    return " ".join(str(value or "").casefold().split())


def _contains_normalized_value(expected_value, output_values):
    return any(
        expected_value == output_value
        or expected_value in output_value
        or output_value in expected_value
        for output_value in output_values
    )


def _list_fields_score(outputs, reference, fields):
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


def _claim_values(payload):
    values = []
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


def _preview_values(values, limit=3):
    if not values:
        return "none"
    return " | ".join(values[:limit])
'''
