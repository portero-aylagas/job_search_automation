from pathlib import Path

from src.prompt_templates import get_prompt, load_prompt_templates


def test_core_project_artifacts_exist() -> None:
    required_paths = [
        "AGENTS.md",
        "PROJECT_SPEC.md",
        "IMPLEMENTATION_PLAN.md",
        "README.md",
        "docs/stories.md",
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
