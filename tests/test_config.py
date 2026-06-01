from __future__ import annotations

import os
from pathlib import Path

from src.config import load_project_environment


def test_load_project_environment_fills_missing_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LANGSMITH_PROJECT=job-search-automation\n"
        "OPENAI_MODEL=gpt-5.4\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert load_project_environment(env_path) is True

    assert os.getenv("LANGSMITH_PROJECT") == "job-search-automation"
    assert os.getenv("OPENAI_MODEL") == "gpt-5.4"


def test_load_project_environment_keeps_exported_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LANGSMITH_PROJECT=dotenv-project\n"
        "OPENAI_MODEL=gpt-5.4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LANGSMITH_PROJECT", "shell-project")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert load_project_environment(env_path) is True

    assert os.getenv("LANGSMITH_PROJECT") == "shell-project"
    assert os.getenv("OPENAI_MODEL") == "gpt-5.4"


def test_load_project_environment_ignores_missing_file(tmp_path: Path) -> None:
    assert load_project_environment(tmp_path / ".env") is False
