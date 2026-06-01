"""Background Browser Use runner that keeps a visible browser open."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
from types import MethodType
from typing import Any

from src.observability import traceable, wrap_openai_client

SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."
APPLY_PAGE_READY_TIMEOUT_SECONDS = 60.0
STABLE_BROWSER_ARGS = [
    "--disable-translate",
    "--disable-features=Translate,TranslateUI",
    "--disable-component-update",
    "--lang=en-US",
]
STABLE_BROWSER_PROFILE_PREFERENCES = {
    "browser": {
        "enable_spellchecking": False,
    },
    "credentials_enable_service": False,
    "intl": {
        "accept_languages": "en-US,en",
    },
    "profile": {
        "default_content_setting_values": {
            "geolocation": 2,
            "notifications": 2,
        },
        "password_manager_enabled": False,
    },
    "translate": {
        "enabled": False,
        "blocked_languages": ["de", "en"],
        "site_blacklist": ["*"],
    },
}
PAGE_READY_CHECK_SCRIPT = """() => {
  const controls = document.querySelectorAll(
    'input, select, textarea, button, [role], [data-testid], [data-test]'
  );
  const bodyText = (document.body?.innerText || '').trim();
  return JSON.stringify({
    bodyTextLength: bodyText.length,
    controlCount: controls.length,
    href: window.location.href,
    readyState: document.readyState,
    title: document.title || ''
  });
}"""


async def open_visible_browser(
    url: str,
    ready_file: Path | None = None,
    agent_task: str | None = None,
    user_data_dir: Path | None = None,
    available_file_paths: list[Path] | None = None,
    require_interactive_page: bool = False,
    page_ready_timeout_seconds: float = APPLY_PAGE_READY_TIMEOUT_SECONDS,
) -> None:
    """Open a URL with Browser Use, optionally run an agent task, then wait."""

    try:
        from browser_use import Agent, Browser
        from browser_use.llm.openai.chat import ChatOpenAI as BrowserUseChatModel
    except ImportError as exc:
        raise RuntimeError(
            "browser-use is not installed. Run `pip install -r requirements.txt` "
            f"and `browser-use install` before opening a Browser Use session. {SETUP_REFERENCE}"
        ) from exc

    if user_data_dir is not None:
        _write_stable_profile_preferences(user_data_dir)

    browser = Browser(
        headless=False,
        keep_alive=True,
        window_size={"width": 1280, "height": 900},
        args=STABLE_BROWSER_ARGS,
        enable_default_extensions=False,
        user_data_dir=user_data_dir,
        env={
            "LANG": "en_US.UTF-8",
            "LANGUAGE": "en_US:en",
            "LC_ALL": "en_US.UTF-8",
        },
    )
    try:
        await browser.start()
        page = await _open_page_with_retries(
            browser,
            url,
            require_interactive_page=require_interactive_page,
            page_ready_timeout_seconds=page_ready_timeout_seconds,
        )
        await _close_other_pages(browser, page)
    except Exception:
        with contextlib.suppress(Exception):
            await browser.stop()
        raise

    if ready_file is not None:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text("ready\n", encoding="utf-8")

    print(f"Opened {url} with Browser Use in visible mode.", flush=True)
    if agent_task:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for Browser Use agent tasks.")
        model = os.getenv("BROWSER_USE_AGENT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
        llm = _build_traced_browser_use_chat_model(
            BrowserUseChatModel,
            model=model,
            temperature=0.2,
            api_key=api_key,
        )
        max_steps = _browser_use_agent_max_steps()
        print(f"Browser Use agent max steps: {max_steps}", flush=True)
        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_session=browser,
            max_actions_per_step=1,
            use_vision="auto",
            source="job_search_automation",
            available_file_paths=[
                str(path)
                for path in available_file_paths or []
                if path.exists()
            ],
        )
        await _run_browser_use_apply_agent(agent, max_steps=max_steps)
        print("Browser Use agent task finished. Browser remains open.", flush=True)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await stop_event.wait()
    await browser.stop()


def main() -> None:
    """Run the visible Browser Use URL opener."""

    parser = argparse.ArgumentParser(description="Open a URL with Browser Use.")
    parser.add_argument("url", help="HTTP or HTTPS URL to open.")
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=None,
        help="Path touched after Browser Use opens the requested page.",
    )
    parser.add_argument(
        "--agent-task",
        default=None,
        help="Optional Browser Use agent task to run after opening the page.",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        help="Isolated Chromium profile directory for this Browser Use run.",
    )
    parser.add_argument(
        "--available-file-path",
        action="append",
        type=Path,
        default=[],
        help="File path the Browser Use agent is allowed to upload.",
    )
    parser.add_argument(
        "--require-interactive-page",
        action="store_true",
        help="Fail startup unless the target page exposes interactive content.",
    )
    parser.add_argument(
        "--page-ready-timeout-seconds",
        type=float,
        default=APPLY_PAGE_READY_TIMEOUT_SECONDS,
        help="Seconds to retry loading an interactive target page.",
    )
    args = parser.parse_args()
    asyncio.run(
        open_visible_browser(
            args.url,
            args.ready_file,
            args.agent_task,
            args.user_data_dir,
            args.available_file_path,
            args.require_interactive_page,
            args.page_ready_timeout_seconds,
        )
    )


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        selected_signal = getattr(signal, signal_name, None)
        if selected_signal is None:
            continue
        try:
            loop.add_signal_handler(selected_signal, stop_event.set)
        except NotImplementedError:
            continue


def _build_traced_browser_use_chat_model(
    chat_model_class: type[Any],
    **kwargs: Any,
) -> Any:
    llm = chat_model_class(**kwargs)
    get_client = llm.get_client

    def traced_get_client(self: object) -> Any:
        return wrap_openai_client(get_client())

    llm.get_client = MethodType(traced_get_client, llm)
    return llm


@traceable("browser_use_apply_agent")
async def _run_browser_use_apply_agent(agent: object, *, max_steps: int) -> object:
    return await agent.run(max_steps=max_steps)


async def _close_existing_pages(browser: object) -> int:
    """Close tabs Browser Use or Chromium opened before the target URL."""

    closed_count = 0
    get_pages = getattr(browser, "get_pages", None)
    close_page = getattr(browser, "close_page", None)
    if get_pages is None or close_page is None:
        return 0

    pages = await get_pages()
    for page in pages:
        with contextlib.suppress(Exception):
            await close_page(page)
            closed_count += 1
    return closed_count


async def _close_other_pages(browser: object, active_page: object) -> int:
    """Close tabs other than the selected target page."""

    active_target_id = _page_target_id(active_page)
    if not active_target_id:
        return 0

    get_pages = getattr(browser, "get_pages", None)
    close_page = getattr(browser, "close_page", None)
    if get_pages is None or close_page is None:
        return 0

    closed_count = 0
    pages = await get_pages()
    for page in pages:
        if _page_target_id(page) == active_target_id:
            continue
        with contextlib.suppress(Exception):
            await close_page(page)
            closed_count += 1

    await _focus_page(browser, active_page)
    return closed_count


async def _open_page_with_retries(
    browser: object,
    url: str,
    *,
    max_attempts: int = 3,
    ready_wait_seconds: float = 4.0,
    poll_interval_seconds: float = 0.5,
    require_interactive_page: bool = False,
    page_ready_timeout_seconds: float = APPLY_PAGE_READY_TIMEOUT_SECONDS,
) -> object:
    """Open a page and retry navigation until real page controls are present."""

    page = await _open_target_page(browser, url)
    if require_interactive_page:
        return await _require_interactive_page(
            browser,
            page,
            url,
            timeout_seconds=page_ready_timeout_seconds,
            retry_interval_seconds=ready_wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    for attempt in range(1, max_attempts + 1):
        if await _wait_for_interactive_page(
            page,
            ready_wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ):
            return page

        if attempt >= max_attempts:
            break

        print(
            f"Page did not expose controls after attempt {attempt}; retrying navigation.",
            flush=True,
        )
        with contextlib.suppress(Exception):
            page = await _navigate_page(browser, page, url)

    print(
        "Page still has no detected controls after navigation retries; "
        "starting Browser Use agent so it can attempt recovery.",
        flush=True,
    )
    return page


async def _open_target_page(browser: object, url: str) -> object:
    navigate_to = getattr(browser, "navigate_to", None)
    get_current_page = getattr(browser, "get_current_page", None)
    if navigate_to is not None and get_current_page is not None:
        with contextlib.suppress(Exception):
            await navigate_to(url, new_tab=False)
            page = await get_current_page()
            if page is not None:
                await _focus_page(browser, page)
                return page

    page = await browser.new_page(url)
    await _focus_page(browser, page)
    return page


async def _require_interactive_page(
    browser: object,
    page: object,
    url: str,
    *,
    timeout_seconds: float,
    retry_interval_seconds: float,
    poll_interval_seconds: float,
) -> object:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    next_retry_at = 0.0
    retry_count = 0
    last_state: dict[str, object] = {}
    retry_interval = max(1.0, retry_interval_seconds)

    while asyncio.get_running_loop().time() < deadline:
        last_state = await _get_page_ready_state(page)
        if _page_ready_state_is_interactive(last_state):
            _log_page_ready_state("Apply page is interactive", last_state)
            await _focus_page(browser, page)
            return page

        now = asyncio.get_running_loop().time()
        if now >= next_retry_at:
            retry_count += 1
            _log_page_ready_state(
                f"Apply page is not interactive; retrying navigation {retry_count}",
                last_state,
            )
            page = await _navigate_page(browser, page, url)
            next_retry_at = now + retry_interval

        await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Browser Use could not load an interactive apply page within "
        f"{timeout_seconds:.0f} seconds. Last page readiness: "
        f"{_format_page_ready_state(last_state)}"
    )


async def _wait_for_interactive_page(
    page: object,
    timeout_seconds: float,
    *,
    poll_interval_seconds: float = 0.5,
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if await _page_has_interactive_content(page):
            return True
        await asyncio.sleep(poll_interval_seconds)
    return False


async def _page_has_interactive_content(page: object) -> bool:
    return _page_ready_state_is_interactive(await _get_page_ready_state(page))


async def _get_page_ready_state(page: object) -> dict[str, object]:
    evaluate = getattr(page, "evaluate", None)
    if evaluate is None:
        return {
            "href": "unavailable",
            "readyState": "unavailable",
            "title": "",
            "bodyTextLength": 1,
            "controlCount": 1,
        }

    try:
        raw_result = await evaluate(PAGE_READY_CHECK_SCRIPT)
    except Exception:
        return {
            "href": "",
            "readyState": "evaluate_failed",
            "title": "",
            "bodyTextLength": 0,
            "controlCount": 0,
        }

    try:
        payload = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError):
        return {
            "href": "",
            "readyState": "invalid_ready_payload",
            "title": "",
            "bodyTextLength": 0,
            "controlCount": 0,
        }

    if not isinstance(payload, dict):
        return {
            "href": "",
            "readyState": "invalid_ready_payload",
            "title": "",
            "bodyTextLength": 0,
            "controlCount": 0,
        }

    return payload


def _page_ready_state_is_interactive(payload: dict[str, object]) -> bool:
    href = str(payload.get("href") or "")
    if not href or href == "about:blank":
        return False

    control_count = _safe_int(payload.get("controlCount"))
    body_text_length = _safe_int(payload.get("bodyTextLength"))
    return control_count > 0 and body_text_length > 0


async def _navigate_page(browser: object, page: object, url: str) -> object:
    goto = getattr(page, "goto", None)
    if goto is not None:
        try:
            await goto(url)
            await _focus_page(browser, page)
            return page
        except Exception as exc:
            print(
                "Page navigation on the current tab failed "
                f"({type(exc).__name__}); retrying Browser Use navigation.",
                flush=True,
            )

    navigate_to = getattr(browser, "navigate_to", None)
    if navigate_to is not None:
        await navigate_to(url, new_tab=False)
        get_current_page = getattr(browser, "get_current_page", None)
        if get_current_page is not None:
            current_page = await get_current_page()
            if current_page is not None:
                await _focus_page(browser, current_page)
                return current_page

    await _focus_page(browser, page)
    return page


async def _focus_page(browser: object, page: object) -> None:
    target_id = _page_target_id(page)
    focus = getattr(browser, "get_or_create_cdp_session", None)
    if not target_id or focus is None:
        return

    with contextlib.suppress(Exception):
        await focus(target_id, focus=True)


def _page_target_id(page: object) -> str:
    return str(getattr(page, "_target_id", "") or "")


def _log_page_ready_state(message: str, payload: dict[str, object]) -> None:
    print(f"{message}: {_format_page_ready_state(payload)}", flush=True)


def _format_page_ready_state(payload: dict[str, object]) -> str:
    href = str(payload.get("href") or "")
    ready_state = str(payload.get("readyState") or "")
    control_count = _safe_int(payload.get("controlCount"))
    body_text_length = _safe_int(payload.get("bodyTextLength"))
    return (
        f"href={href or '<empty>'}, readyState={ready_state or '<empty>'}, "
        f"bodyTextLength={body_text_length}, controlCount={control_count}"
    )


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _write_stable_profile_preferences(user_data_dir: Path) -> None:
    default_profile_dir = user_data_dir / "Default"
    default_profile_dir.mkdir(parents=True, exist_ok=True)
    _merge_json_file(
        default_profile_dir / "Preferences",
        STABLE_BROWSER_PROFILE_PREFERENCES,
    )
    _merge_json_file(
        user_data_dir / "Local State",
        {
            "translate": {
                "enabled": False,
            },
            "intl": {
                "app_locale": "en-US",
            },
        },
    )


def _browser_use_agent_max_steps() -> int:
    raw_value = os.getenv("BROWSER_USE_AGENT_MAX_STEPS", "").strip()
    if not raw_value:
        return 120
    try:
        max_steps = int(raw_value)
    except ValueError:
        return 120
    return max(20, max_steps)


def _merge_json_file(path: Path, updates: dict[str, object]) -> None:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    _deep_merge(payload, updates)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _deep_merge(target: dict[str, object], updates: dict[str, object]) -> None:
    for key, value in updates.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(existing, value)
        else:
            target[key] = value


if __name__ == "__main__":
    main()
