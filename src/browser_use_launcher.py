"""Launch visible Browser Use sessions for assisted job intake."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

STARTUP_WAIT_SECONDS = 30.0
STARTUP_POLL_SECONDS = 0.25
SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."


@dataclass(frozen=True)
class BrowserUseOpenResult:
    """Result returned after starting a visible Browser Use session."""

    url: str
    pid: int
    log_path: Path


class BrowserUseLaunchError(RuntimeError):
    """Raised when Browser Use cannot open a visible browser session."""


def open_url_with_browser_use(
    url: str,
    *,
    log_dir: Path | str,
    startup_wait_seconds: float = STARTUP_WAIT_SECONDS,
) -> BrowserUseOpenResult:
    """Open a URL in a visible Browser Use browser process.

    Args:
        url: HTTP or HTTPS URL to open.
        log_dir: Directory where the background process log is written.
        startup_wait_seconds: Seconds to wait for immediate startup failures.

    Returns:
        Metadata for the launched background process.

    Raises:
        BrowserUseLaunchError: If the URL is invalid or Browser Use exits early.
    """

    normalized_url = _require_http_url(url)
    target_log_dir = Path(log_dir)
    target_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_log_dir / _build_log_filename()
    ready_path = log_path.with_suffix(".ready")
    browser_use_env = _browser_use_environment(target_log_dir)
    repo_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "src.browser_use_visible_runner",
        normalized_url,
        "--ready-file",
        str(ready_path),
    ]

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=browser_use_env,
        )

    _wait_for_browser_ready(process, log_path, ready_path, startup_wait_seconds)

    return BrowserUseOpenResult(url=normalized_url, pid=process.pid, log_path=log_path)


def _require_http_url(url: str) -> str:
    normalized_url = url.strip()
    if not normalized_url:
        raise BrowserUseLaunchError("Enter a job URL before opening Browser Use.")

    parsed = urlsplit(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserUseLaunchError("Browser Use can only open a valid http or https URL.")
    return normalized_url


def _build_log_filename() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"browser-use-job-intake-{timestamp}.log"


def _browser_use_environment(runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["BROWSER_USE_CONFIG_DIR"] = str(runtime_dir / "config")
    env["XDG_CACHE_HOME"] = str(runtime_dir / "cache")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "playwright-browsers")
    return env


def _wait_for_browser_ready(
    process: subprocess.Popen,
    log_path: Path,
    ready_path: Path,
    startup_wait_seconds: float,
) -> None:
    if startup_wait_seconds <= 0:
        if process.poll() is not None:
            _raise_startup_error(log_path)
        return

    deadline = time.monotonic() + startup_wait_seconds
    while time.monotonic() < deadline:
        if ready_path.exists():
            return
        if process.poll() is not None:
            _raise_startup_error(log_path)
        time.sleep(STARTUP_POLL_SECONDS)

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
    _raise_startup_error(
        log_path,
        prefix=(
            "Browser Use did not confirm the page opened before the startup timeout. "
            "Check that its browser runtime is installed. "
            f"{SETUP_REFERENCE}"
        ),
    )


def _raise_startup_error(
    log_path: Path,
    *,
    prefix: str = (
        "Browser Use failed to open the URL. "
        "Install Browser Use and its browser runtime, then try again. "
        f"{SETUP_REFERENCE}"
    ),
) -> None:
    log_tail = _tail_text(log_path)
    if log_tail:
        prefix = f"{prefix}\n\nRecent Browser Use log:\n{log_tail}"
    raise BrowserUseLaunchError(prefix)


def _tail_text(path: Path, *, max_chars: int = 2000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:].strip()
