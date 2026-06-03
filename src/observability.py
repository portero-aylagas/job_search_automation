"""Optional observability helpers for AI workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])

_TRUE_VALUES = {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    """Return True when LangSmith tracing is explicitly enabled."""

    return bool(os.getenv("LANGSMITH_API_KEY")) and (
        os.getenv("LANGSMITH_TRACING", "").strip().lower() in _TRUE_VALUES
    )


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI client with LangSmith tracing when available."""

    if not langsmith_enabled():
        return client

    try:
        from langsmith.wrappers import wrap_openai
    except ImportError:
        return client

    return wrap_openai(client)


def traceable(name: str, *, run_type: str = "chain") -> Callable[[F], F]:
    """Trace a function with LangSmith when tracing is enabled."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not langsmith_enabled():
                return func(*args, **kwargs)

            try:
                from langsmith import traceable as langsmith_traceable
            except ImportError:
                return func(*args, **kwargs)

            traced_func = langsmith_traceable(name=name, run_type=run_type)(func)
            return traced_func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator
