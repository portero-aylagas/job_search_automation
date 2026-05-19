from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter


def ensure_data_dirs(base_dir: Path | str = ".") -> None:
    root = Path(base_dir)
    for relative_path in ("data", "data/jobs", "data/applications", "outputs"):
        (root / relative_path).mkdir(parents=True, exist_ok=True)


def save_json(path: Path | str, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=True)
        file.write("\n")


def load_json(path: Path | str, default: Any | None = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    with target.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_model(path: Path | str, model: Any) -> None:
    if isinstance(model, BaseModel):
        payload = model.model_dump(mode="json")
    else:
        payload = TypeAdapter(type(model)).dump_python(model, mode="json")
    save_json(path, payload)


def load_model(path: Path | str, model_type: Any, default: Any | None = None) -> Any:
    payload = load_json(path, default=default)
    if payload is default:
        return default
    return TypeAdapter(model_type).validate_python(payload)
