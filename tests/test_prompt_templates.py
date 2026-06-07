from __future__ import annotations

import pytest

from src import prompt_templates
from src.prompt_templates import get_prompt, get_prompt_template_metadata


def test_get_prompt_preserves_braces_inside_variable_values() -> None:
    rendered = get_prompt(
        "llm_job_extraction",
        "extract_job_data",
        "user",
        normalized_url="https://example.com/jobs/{job_id}?q={ignore_this}",
    )

    assert "https://example.com/jobs/{job_id}?q={ignore_this}" in rendered


def test_get_prompt_reports_missing_template_variable() -> None:
    with pytest.raises(KeyError, match="normalized_url"):
        get_prompt("llm_job_extraction", "extract_job_data", "user")


def test_get_prompt_reports_missing_template_path() -> None:
    with pytest.raises(KeyError, match="Prompt template not found"):
        get_prompt("missing", "template")


def test_get_prompt_rejects_non_string_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prompt_templates,
        "load_prompt_templates",
        lambda: {"section": {"node": {"not": "a string"}}},
    )

    with pytest.raises(TypeError, match="Prompt template must be a string"):
        get_prompt("section", "node")


def test_get_prompt_renders_large_serialized_payload_without_truncating() -> None:
    payload = '{"items":[' + ",".join(f'"value-{index}"' for index in range(250)) + "]}"

    rendered = get_prompt(
        "apply_url_resolution",
        "rank_candidates",
        "user",
        evidence_json=payload,
    )

    assert payload in rendered
    assert "value-249" in rendered


def test_application_requirements_prompt_preserves_grouped_attachment_needs() -> None:
    rendered = get_prompt("application_requirements", "extract_requirements", "system")

    assert "CV, cover letter, certificates, references" in rendered
    assert "separate CV, cover letter, certificate, and reference needs" in rendered


def test_prompt_template_metadata_hashes_template_node_without_rendering_variables() -> None:
    metadata = get_prompt_template_metadata("application_package", "generate_package")

    assert metadata["prompt_template_name"] == "application_package.generate_package"
    assert metadata["prompt_template_version"] is None
    assert metadata["prompt_template_hash"]
    assert metadata["prompt_template_hash"].startswith("sha256:")
    assert "{manifest_json}" not in metadata["prompt_template_hash"]


def test_prompt_template_metadata_reports_missing_template_path() -> None:
    with pytest.raises(KeyError, match="Prompt template not found"):
        get_prompt_template_metadata("missing", "template")
