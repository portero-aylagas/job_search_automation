"""Optional observability helpers for AI workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeAlias, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])
MetadataFactory: TypeAlias = Callable[..., dict[str, Any]]

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


def set_current_trace_metadata(metadata: dict[str, Any]) -> None:
    """Best-effort update of metadata on the active LangSmith trace."""

    if not metadata:
        return
    safe_metadata = _trace_metadata(metadata)
    if not safe_metadata:
        return
    try:
        from langsmith.run_helpers import set_run_metadata
    except ImportError:
        return
    try:
        set_run_metadata(**safe_metadata)
    except Exception:
        return


def traceable(
    name: str,
    *,
    run_type: str = "chain",
    tags: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | MetadataFactory | None = None,
) -> Callable[[F], F]:
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

            trace_kwargs: dict[str, Any] = {"name": name, "run_type": run_type}
            if tags:
                trace_kwargs["tags"] = list(tags)
            safe_metadata = _trace_metadata(metadata, *args, **kwargs)
            if safe_metadata:
                trace_kwargs["metadata"] = safe_metadata
            traced_func = langsmith_traceable(**trace_kwargs)(func)
            return traced_func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


def _trace_metadata(
    metadata: dict[str, Any] | MetadataFactory | None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return JSON-safe trace metadata, ignoring metadata factory failures."""

    if metadata is None:
        return {}
    try:
        raw_metadata = metadata(*args, **kwargs) if callable(metadata) else metadata
    except Exception:
        return {}
    if not isinstance(raw_metadata, dict):
        return {}
    return {
        str(key): value
        for key, value in raw_metadata.items()
        if str(key).strip() and _metadata_value_is_safe(value)
    }


def _metadata_value_is_safe(value: Any) -> bool:
    """Return True for small scalar/list metadata values safe for tracing."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_metadata_value_is_safe(item) for item in value)
    if isinstance(value, tuple):
        return all(_metadata_value_is_safe(item) for item in value)
    return False
