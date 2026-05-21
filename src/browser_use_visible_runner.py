"""Background Browser Use runner that keeps a visible browser open."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path

SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."
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


async def open_visible_browser(
    url: str,
    ready_file: Path | None = None,
    agent_task: str | None = None,
    user_data_dir: Path | None = None,
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
        await _close_existing_pages(browser)
        await browser.new_page(url)
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
        llm = BrowserUseChatModel(model=model, temperature=0.2, api_key=api_key)
        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_session=browser,
            max_actions_per_step=1,
            use_vision="auto",
            source="job_search_automation",
        )
        await agent.run(max_steps=40)
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
    args = parser.parse_args()
    asyncio.run(
        open_visible_browser(
            args.url,
            args.ready_file,
            args.agent_task,
            args.user_data_dir,
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
