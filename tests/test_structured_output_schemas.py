from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from src.agents.karen.state import KarenIntentResponse
from src.application_fill_plan import LLMApplicationFieldMappingResponse
from src.application_package import LLMApplicationPackageResponse
from src.application_requirements import LLMApplicationRequirementsResponse
from src.cv_extraction import (
    LLMCandidateCVExtractedResponse,
    LLMCandidateSupplementalExtractedResponse,
)
from src.llm_job_extraction import (
    LLMApplyUrlResolutionResponse,
    LLMExtractedJobDataResponse,
)
from src.workflow.workflow_planner import WorkflowIntent


@dataclass(frozen=True)
class SchemaContract:
    name: str
    model: type[BaseModel]
    properties: tuple[str, ...]


AI_RESPONSE_SCHEMA_CONTRACTS = (
    SchemaContract(
        name="cv extraction",
        model=LLMCandidateCVExtractedResponse,
        properties=(
            "identity",
            "work_experience",
            "education",
            "skills",
            "languages",
            "certifications",
            "projects",
            "references",
        ),
    ),
    SchemaContract(
        name="optional document extraction",
        model=LLMCandidateSupplementalExtractedResponse,
        properties=(
            "work_experience",
            "education",
            "skills",
            "languages",
            "certifications",
            "projects",
            "references",
            "notes",
        ),
    ),
    SchemaContract(
        name="job extraction",
        model=LLMExtractedJobDataResponse,
        properties=(
            "title",
            "company",
            "location",
            "remote_policy",
            "apply_url",
            "description",
            "requirements",
            "responsibilities",
            "nice_to_have_skills",
            "salary",
            "posted_date",
            "source_job_id",
            "confidence",
            "dynamic_fields",
            "missing_or_uncertain",
        ),
    ),
    SchemaContract(
        name="apply URL ranking/resolution",
        model=LLMApplyUrlResolutionResponse,
        properties=(
            "status",
            "apply_url",
            "notes",
            "evidence",
            "rejected_candidates",
            "confidence",
        ),
    ),
    SchemaContract(
        name="application requirements",
        model=LLMApplicationRequirementsResponse,
        properties=(
            "job_id",
            "apply_url",
            "source_url",
            "status",
            "blocked_reason",
            "job_preserving",
            "required_documents",
            "upload_expectations",
            "screening_questions",
            "custom_form_fields",
            "profile_fields",
            "motivation_letter",
            "consent_requirements",
            "privacy_login_ats_gates",
            "deadlines",
            "contact_or_fallback",
            "missing_or_uncertain",
            "source_evidence",
            "confidence",
        ),
    ),
    SchemaContract(
        name="application package",
        model=LLMApplicationPackageResponse,
        properties=(
            "job_id",
            "status",
            "artifacts",
            "missing_information",
            "selected_experience_units",
            "generation_notes",
        ),
    ),
    SchemaContract(
        name="fill-plan field mapping",
        model=LLMApplicationFieldMappingResponse,
        properties=("suggestions",),
    ),
    SchemaContract(
        name="Karen intent classification",
        model=KarenIntentResponse,
        properties=(
            "assistant_message",
            "workflow_intent",
            "proposed_tool",
            "permission_level",
            "auto_execute",
            "target_job_id",
            "route_page",
            "permission_grant",
            "safety_reason",
        ),
    ),
    SchemaContract(
        name="Karen workflow intent classification",
        model=WorkflowIntent,
        properties=(
            "goal",
            "target_job_id",
            "allow_draft_generation",
            "allow_local_mutations",
            "allow_review_gate_crossing",
            "allow_browser_launch",
            "execution_mode",
            "confidence",
            "reasoning_summary",
            "requires_clarification",
            "clarification_question",
        ),
    ),
)

FORBIDDEN_FREE_FORM_FIELDS = {
    "metadata",
    "job_details",
    "source_metadata",
    "event_details",
    "details",
    "raw_json",
    "raw_response",
    "extra",
}


@pytest.mark.parametrize("contract", AI_RESPONSE_SCHEMA_CONTRACTS, ids=lambda item: item.name)
def test_ai_response_strict_schemas_keep_required_top_level_contract(
    contract: SchemaContract,
) -> None:
    schema = to_strict_json_schema(contract.model)

    assert tuple(schema["properties"].keys()) == contract.properties
    assert tuple(schema["required"]) == contract.properties
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("contract", AI_RESPONSE_SCHEMA_CONTRACTS, ids=lambda item: item.name)
def test_ai_response_strict_schemas_are_closed_and_openai_compatible(
    contract: SchemaContract,
) -> None:
    schema = to_strict_json_schema(contract.model)

    for path, object_schema in _iter_object_schemas(schema):
        properties = object_schema.get("properties", {})
        assert object_schema.get("additionalProperties") is False, path
        assert object_schema.get("required", []) == list(properties), path


@pytest.mark.parametrize("contract", AI_RESPONSE_SCHEMA_CONTRACTS, ids=lambda item: item.name)
def test_ai_response_schemas_do_not_include_broad_free_form_metadata(
    contract: SchemaContract,
) -> None:
    schema = to_strict_json_schema(contract.model)

    for path, object_schema in _iter_object_schemas(schema):
        properties = object_schema.get("properties", {})
        forbidden_fields = FORBIDDEN_FREE_FORM_FIELDS.intersection(properties)
        assert forbidden_fields == set(), path

        for property_name, property_schema in properties.items():
            assert not _is_free_form_object(property_schema), f"{path}.{property_name}"


def test_job_and_apply_url_schemas_keep_expected_enums() -> None:
    job_schema = to_strict_json_schema(LLMExtractedJobDataResponse)
    apply_url_schema = to_strict_json_schema(LLMApplyUrlResolutionResponse)

    assert _property_has_enum(job_schema, "confidence", {"high", "medium", "low"})
    assert _def_property_has_enum(
        job_schema,
        "DynamicJobDetail",
        "confidence",
        {"high", "medium", "low"},
    )
    assert _property_has_enum(
        apply_url_schema,
        "status",
        {"resolved", "needs_review", "not_found"},
    )
    assert _property_has_enum(apply_url_schema, "confidence", {"high", "medium", "low"})


def test_application_requirements_schema_keeps_expected_enums() -> None:
    schema = to_strict_json_schema(LLMApplicationRequirementsResponse)

    assert _property_has_enum(schema, "status", {"discovered", "blocked"})
    assert _property_has_enum(schema, "confidence", {"high", "medium", "low"})
    for definition_name in (
        "ApplicationRequirementFinding",
        "ApplicationScreeningQuestion",
        "ApplicationFormField",
    ):
        assert _def_property_has_enum(
            schema,
            definition_name,
            "confidence",
            {"high", "medium", "low"},
        )


def test_application_package_schema_keeps_expected_enums() -> None:
    schema = to_strict_json_schema(LLMApplicationPackageResponse)

    assert _property_has_enum(schema, "status", {"draft", "needs_review"})
    assert _def_property_has_enum(
        schema,
        "LLMApplicationArtifact",
        "status",
        {"draft", "needs_review"},
    )


def test_fill_plan_field_mapping_schema_keeps_expected_enums() -> None:
    schema = to_strict_json_schema(LLMApplicationFieldMappingResponse)

    assert _def_property_has_enum(
        schema,
        "ApplicationFieldMappingSuggestion",
        "action",
        {"fill", "skip_duplicate", "block"},
    )
    assert _def_property_has_enum(
        schema,
        "ApplicationFieldMappingSuggestion",
        "confidence",
        {"high", "medium", "low"},
    )


def test_karen_intent_schemas_keep_expected_enums() -> None:
    intent_schema = to_strict_json_schema(KarenIntentResponse)
    workflow_schema = to_strict_json_schema(WorkflowIntent)
    workflow_goals = {
        "generate_application_data",
        "mark_current_gate_reviewed",
        "generate_and_review_application_data",
        "continue_to_next_gate",
        "continue_until_blocked",
        "prepare_browser_application",
        "launch_browser_application",
        "prepare_manual_application",
        "apply_without_browser_use",
        "stop_browser_session",
    }

    assert _property_has_enum(
        intent_schema,
        "permission_level",
        {
            "READ_ONLY",
            "DRAFT_ONLY",
            "MUTATES_LOCAL_STATE",
            "EXTERNAL_BROWSER_ACTION",
        },
    )
    assert _property_has_enum(workflow_schema, "goal", workflow_goals)
    assert _property_has_enum(workflow_schema, "execution_mode", {"manual", "browser_use"})
    assert _property_has_enum(workflow_schema, "confidence", {"low", "medium", "high"})
    assert _def_property_has_enum(intent_schema, "WorkflowIntent", "goal", workflow_goals)
    assert _def_property_has_enum(
        intent_schema,
        "WorkflowIntent",
        "execution_mode",
        {"manual", "browser_use"},
    )


def _iter_object_schemas(schema: dict[str, Any], path: str = "$"):
    if _is_object_schema(schema):
        yield path, schema

    for definition_name, definition in schema.get("$defs", {}).items():
        yield from _iter_object_schemas(definition, f"{path}.$defs.{definition_name}")

    for property_name, property_schema in schema.get("properties", {}).items():
        yield from _iter_object_schemas(property_schema, f"{path}.{property_name}")

    for keyword in ("anyOf", "oneOf", "allOf"):
        for index, child in enumerate(schema.get(keyword, [])):
            yield from _iter_object_schemas(child, f"{path}.{keyword}[{index}]")

    items = schema.get("items")
    if isinstance(items, dict):
        yield from _iter_object_schemas(items, f"{path}.items")


def _is_object_schema(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "object" or "properties" in schema


def _is_free_form_object(schema: dict[str, Any]) -> bool:
    if _is_nullable(schema):
        return any(
            _is_free_form_object(option)
            for option in schema.get("anyOf", [])
            if option.get("type") != "null"
        )
    if "$ref" in schema or schema.get("items"):
        return False
    if schema.get("type") != "object":
        return False
    return not schema.get("properties")


def _is_nullable(schema: dict[str, Any]) -> bool:
    return isinstance(schema.get("anyOf"), list)


def _property_has_enum(
    schema: dict[str, Any],
    property_name: str,
    expected_values: set[str],
) -> bool:
    property_schema = schema["properties"][property_name]
    return _schema_has_enum(schema, property_schema, expected_values)


def _def_property_has_enum(
    schema: dict[str, Any],
    definition_name: str,
    property_name: str,
    expected_values: set[str],
) -> bool:
    property_schema = schema["$defs"][definition_name]["properties"][property_name]
    return _schema_has_enum(schema, property_schema, expected_values)


def _schema_has_enum(
    root_schema: dict[str, Any],
    schema: dict[str, Any],
    expected_values: set[str],
) -> bool:
    if set(schema.get("enum", [])) == expected_values:
        return True
    if "$ref" in schema:
        return _schema_has_enum(
            root_schema,
            _resolve_ref(root_schema, schema["$ref"]),
            expected_values,
        )
    return any(
        _schema_has_enum(root_schema, option, expected_values)
        for keyword in ("anyOf", "oneOf", "allOf")
        for option in schema.get(keyword, [])
    )


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise AssertionError(f"Unsupported schema ref: {ref}")
    return root_schema["$defs"][ref.removeprefix(prefix)]
