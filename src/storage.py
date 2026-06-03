"""JSON file storage helpers for the local application state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from src.paths import (
    AGENT_RUNS_DIR,
    AGENT_SESSIONS_DIR,
    DATA_DIR,
    OUTPUTS_DIR,
    RUNTIME_DATA_DIR,
    RUNTIME_JOBS_DIR,
    TEMPLATE_JOBS_DIR,
)


class JsonStorageError(ValueError):
    """Raised when a JSON storage file exists but cannot be decoded."""

    pass


def ensure_data_dirs(base_dir: Path | str = ".") -> None:
    """Create the local data and output directories used by the workflow.

    Args:
        base_dir: Repository or test root where runtime directories should be
            created.
    """

    root = Path(base_dir)
    for relative_path in (
        DATA_DIR,
        TEMPLATE_JOBS_DIR,
        RUNTIME_DATA_DIR,
        RUNTIME_JOBS_DIR,
        AGENT_SESSIONS_DIR,
        AGENT_RUNS_DIR,
        OUTPUTS_DIR,
    ):
        (root / relative_path).mkdir(parents=True, exist_ok=True)


def save_json(path: Path | str, data: Any) -> None:
    """Write JSON data to disk and create missing parent directories.

    Args:
        path: Destination JSON file path.
        data: JSON-serializable payload to persist.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=True)
        file.write("\n")


def load_json(path: Path | str, default: Any | None = None) -> Any:
    """Load JSON data from disk or return the caller-provided default.

    Args:
        path: Source JSON file path.
        default: Value returned when the file does not exist.

    Raises:
        JsonStorageError: If the file exists but contains malformed JSON.
    """

    target = Path(path)
    if not target.exists():
        return default
    with target.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as exc:
            raise JsonStorageError(
                f"Invalid JSON in {target}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc


def save_model(path: Path | str, model: Any) -> None:
    """Serialize a Pydantic-compatible model as JSON at the given path.

    Args:
        path: Destination JSON file path.
        model: Pydantic model or type-adaptable object to persist.
    """

    if isinstance(model, BaseModel):
        payload = model.model_dump(mode="json")
    else:
        payload = TypeAdapter(type(model)).dump_python(model, mode="json")
    save_json(path, payload)


def load_model(path: Path | str, model_type: Any, default: Any | None = None) -> Any:
    """Load JSON from disk and validate it as the requested model type.

    Args:
        path: Source JSON file path.
        model_type: Pydantic model type or supported type annotation.
        default: Value returned when the file does not exist.

    Returns:
        The validated model instance or the provided default.
    """

    payload = load_json(path, default=default)
    if payload is default:
        return default
    return TypeAdapter(model_type).validate_python(payload)


def append_jsonl(path: Path | str, data: Any) -> None:
    """Append one JSON-serializable record to a JSON Lines file.

    Args:
        path: Destination JSONL file path.
        data: JSON-serializable payload to append.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=True)
        file.write("\n")


def load_jsonl(path: Path | str) -> list[Any]:
    """Load all valid JSON Lines records from a file.

    Args:
        path: Source JSONL file path.

    Raises:
        JsonStorageError: If any existing line contains malformed JSON.
    """

    target = Path(path)
    if not target.exists():
        return []

    records: list[Any] = []
    with target.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            try:
                records.append(json.loads(stripped_line))
            except json.JSONDecodeError as exc:
                raise JsonStorageError(
                    f"Invalid JSONL in {target}: line {line_number}: {exc.msg}"
                ) from exc
    return records
