from pathlib import Path


def test_core_project_artifacts_exist() -> None:
    required_paths = [
        "AGENTS.md",
        "PROJECT_SPEC.md",
        "IMPLEMENTATION_PLAN.md",
        "README.md",
        "docs/stories.md",
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
