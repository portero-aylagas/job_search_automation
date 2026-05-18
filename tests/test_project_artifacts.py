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
