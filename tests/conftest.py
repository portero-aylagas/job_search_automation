from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIVE_AI_MARKER = "live_ai"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-ai",
        action="store_true",
        default=False,
        help="Run tests marked live_ai and allow live AI provider client construction.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-ai"):
        return

    skip_live_ai = pytest.mark.skip(reason="requires --run-live-ai")
    for item in items:
        if item.get_closest_marker(LIVE_AI_MARKER) is not None:
            item.add_marker(skip_live_ai)


@pytest.fixture(autouse=True)
def block_live_ai_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    if _live_ai_allowed(request):
        return

    try:
        import openai
    except ImportError:
        return

    for constructor_name in (
        "OpenAI",
        "AsyncOpenAI",
        "AzureOpenAI",
        "AsyncAzureOpenAI",
    ):
        monkeypatch.setattr(
            openai,
            constructor_name,
            _blocked_live_ai_provider_constructor,
            raising=False,
        )


def _live_ai_allowed(request: pytest.FixtureRequest) -> bool:
    return bool(
        request.config.getoption("--run-live-ai")
        and request.node.get_closest_marker(LIVE_AI_MARKER) is not None
    )


def _blocked_live_ai_provider_constructor(*_args: object, **_kwargs: object) -> None:
    raise AssertionError(
        "Live OpenAI provider construction is blocked during normal tests. "
        "Mock src.llm_client.get_openai_client for unit tests, or mark an explicit "
        "manual test with @pytest.mark.live_ai and run pytest with --run-live-ai."
    )
