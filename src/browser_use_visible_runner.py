"""Background Browser Use runner that keeps a visible browser open."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from pathlib import Path

SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."


async def open_visible_browser(url: str, ready_file: Path | None = None) -> None:
    """Open a URL with Browser Use using ``headless=False`` and wait until stopped."""

    try:
        from browser_use import Browser
    except ImportError as exc:
        raise RuntimeError(
            "browser-use is not installed. Run `pip install -r requirements.txt` "
            f"and `browser-use install` before opening a Browser Use session. {SETUP_REFERENCE}"
        ) from exc

    browser = Browser(
        headless=False,
        keep_alive=True,
        window_size={"width": 1280, "height": 900},
    )
    try:
        await browser.start()
        await browser.new_page(url)
    except Exception:
        with contextlib.suppress(Exception):
            await browser.stop()
        raise

    if ready_file is not None:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text("ready\n", encoding="utf-8")

    print(f"Opened {url} with Browser Use in visible mode.", flush=True)

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
    args = parser.parse_args()
    asyncio.run(open_visible_browser(args.url, args.ready_file))


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


if __name__ == "__main__":
    main()
