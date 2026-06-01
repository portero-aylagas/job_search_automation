"""Configuration loading for local development and runtime entry points."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_environment(env_path: Path | str | None = None) -> bool:
    """Load repo-local environment variables without overriding shell values.

    Args:
        env_path: Optional explicit `.env` path. Defaults to the repository root.

    Returns:
        True when a dotenv file was found and parsed.
    """

    target_path = Path(env_path) if env_path is not None else PROJECT_ROOT / ".env"
    if not target_path.exists():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        return False

    return bool(load_dotenv(dotenv_path=target_path, override=False))
