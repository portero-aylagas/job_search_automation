from __future__ import annotations

import os
from typing import Any

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_openai_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before extracting job data with AI.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    return OpenAI()
