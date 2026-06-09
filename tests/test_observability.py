from __future__ import annotations

import sys
from types import ModuleType

from src.observability import langsmith_enabled, traceable, wrap_openai_client


def test_langsmith_disabled_without_tracing_flag(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    assert langsmith_enabled() is False


def test_wrap_openai_client_returns_original_when_disabled(monkeypatch) -> None:
    client = object()
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    assert wrap_openai_client(client) is client


def test_wrap_openai_client_uses_langsmith_when_enabled(monkeypatch) -> None:
    client = object()
    wrapped_client = object()
    wrappers_module = ModuleType("langsmith.wrappers")

    def fake_wrap_openai(candidate: object) -> object:
        return wrapped_client if candidate is client else candidate

    wrappers_module.wrap_openai = fake_wrap_openai
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", wrappers_module)
    monkeypatch.setattr("src.observability.langsmith_enabled", lambda: True)

    assert wrap_openai_client(client) is wrapped_client


def test_wrap_openai_client_falls_back_when_langsmith_unavailable(monkeypatch) -> None:
    client = object()
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "langsmith.wrappers":
            raise ImportError("langsmith unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr("src.observability.langsmith_enabled", lambda: True)

    assert wrap_openai_client(client) is client


def test_traceable_uses_named_langsmith_span_when_enabled(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    langsmith_module = ModuleType("langsmith")

    def fake_traceable(**kwargs):
        calls.append(kwargs)

        def decorator(func):
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    langsmith_module.traceable = fake_traceable
    monkeypatch.setitem(sys.modules, "langsmith", langsmith_module)
    monkeypatch.setattr("src.observability.langsmith_enabled", lambda: True)

    @traceable(
        "parent_span",
        run_type="chain",
        tags=("workflow:test",),
        metadata=lambda value: {"workflow_key": "test", "unsafe": {"nested": True}},
    )
    def traced_function(value: str) -> str:
        return "ok"

    assert traced_function("ignored") == "ok"
    assert calls == [
        {
            "name": "parent_span",
            "run_type": "chain",
            "tags": ["workflow:test"],
            "metadata": {"workflow_key": "test"},
        }
    ]
