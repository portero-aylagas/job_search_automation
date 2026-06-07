"""Load and render versioned prompt templates from the repository YAML file."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_PATH = Path(__file__).with_name("prompts.yaml")


@lru_cache(maxsize=1)
def load_prompt_templates() -> dict[str, Any]:
    """Load the repository prompt templates from YAML."""
    with PROMPTS_PATH.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Prompt templates must be a mapping: {PROMPTS_PATH}")
    return payload


def get_prompt(*path: str, **variables: object) -> str:
    """Return a rendered prompt template looked up by nested YAML path."""
    node: Any = load_prompt_templates()
    joined_path = ".".join(path)

    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"Prompt template not found: {joined_path}")
        node = node[key]

    if not isinstance(node, str):
        raise TypeError(f"Prompt template must be a string: {joined_path}")

    try:
        return node.format(**variables)
    except KeyError as exc:
        missing_name = exc.args[0]
        raise KeyError(
            f"Prompt template '{joined_path}' is missing variable '{missing_name}'"
        ) from exc


def get_prompt_template_metadata(*path: str) -> dict[str, str | None]:
    """Return stable trace metadata for a prompt template path."""
    node: Any = load_prompt_templates()
    joined_path = ".".join(path)

    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"Prompt template not found: {joined_path}")
        node = node[key]

    version = _prompt_template_version(node)
    template_payload = _prompt_template_hash_payload(node)
    encoded = json.dumps(
        template_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "prompt_template_name": joined_path,
        "prompt_template_version": version,
        "prompt_template_hash": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    }


def _prompt_template_version(node: object) -> str | None:
    if not isinstance(node, dict):
        return None
    version = node.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return None


def _prompt_template_hash_payload(node: object) -> object:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return {
            str(key): _prompt_template_hash_payload(value)
            for key, value in sorted(node.items())
            if key != "version"
        }
    if isinstance(node, list):
        return [_prompt_template_hash_payload(item) for item in node]
    return node
