from pathlib import Path

from src.prompt_templates import get_prompt, load_prompt_templates


def test_core_project_artifacts_exist() -> None:
    required_paths = [
        "AGENTS.md",
        "PROJECT_SPEC.md",
        "IMPLEMENTATION_PLAN.md",
        "README.md",
        "docs/stories.md",
        "docs/development_standards.md",
        ".env.example",
    ]

    missing = [path for path in required_paths if not Path(path).is_file()]

    assert not missing, f"Missing required project artifact(s): {', '.join(missing)}"


def test_llm_provider_calls_stay_behind_llm_client() -> None:
    allowed_provider_file = Path("src/llm_client.py")
    forbidden_patterns = ("responses.parse", "OpenAI(")
    violations: list[str] = []

    for path in Path("src").glob("*.py"):
        if path == allowed_provider_file:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{path}: {pattern}")

    assert not violations, "Provider calls must stay in src/llm_client.py: " + ", ".join(
        violations
    )


def test_prompt_templates_exist_and_render() -> None:
    templates = load_prompt_templates()

    assert isinstance(templates, dict)
    assert Path("src/prompts.yaml").is_file()
    assert "candidate CV" in get_prompt("cv_extraction", "extract_cv_data", "system")
    assert "https://example.com/job" in get_prompt(
        "llm_job_extraction",
        "extract_job_data",
        "user",
        normalized_url="https://example.com/job",
    )


def test_env_example_documents_required_ai_settings() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY=your-openai-api-key-here" in env_example
    assert "OPENAI_MODEL=gpt-5.4" in env_example


def test_delivery_status_docs_are_consistent() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    implementation_plan = Path("IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")

    assert "## Delivered Features" in readme
    assert "deterministic candidate/job match analysis" in readme
    assert "deterministic match analysis (pending)" in readme
    assert "Application package generation is implemented" in implementation_plan
    assert "Deterministic match analysis is still pending." in implementation_plan
    assert "Application package generation and downstream human review are still pending" not in (
        implementation_plan
    )


def test_development_standards_document_hygiene_and_skill_boundaries() -> None:
    standards = Path("docs/development_standards.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Repository Hygiene Standards" in standards
    assert "Documentation Standards" in standards
    assert "Skill Boundary" in standards
    assert "data/runtime/" in standards
    assert "data/candidate_profile.json" in standards
    assert "outputs/" in standards
    assert "development/support skill" in standards
    assert "docs/development_standards.md" in readme
