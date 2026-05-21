"""Launch visible Browser Use sessions for assisted job intake."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from src.schemas import CandidateProfile

STARTUP_WAIT_SECONDS = 30.0
STARTUP_POLL_SECONDS = 0.25
SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."


@dataclass(frozen=True)
class BrowserUseOpenResult:
    """Result returned after starting a visible Browser Use session or task."""

    url: str
    pid: int
    log_path: Path


@dataclass(frozen=True)
class BrowserUseSession:
    """Persisted metadata for one active Browser Use background session."""

    url: str
    pid: int
    log_path: Path
    started_at: str


class BrowserUseLaunchError(RuntimeError):
    """Raised when Browser Use cannot open a visible browser session."""


def get_active_browser_use_session(log_dir: Path | str) -> BrowserUseSession | None:
    """Return the active Browser Use session if its process is still running."""

    session_path = _active_session_path(log_dir)
    if not session_path.exists():
        return None

    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        session = BrowserUseSession(
            url=str(payload["url"]),
            pid=int(payload["pid"]),
            log_path=Path(str(payload["log_path"])),
            started_at=str(payload["started_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        session_path.unlink(missing_ok=True)
        return None

    if _is_process_running(session.pid):
        return session

    session_path.unlink(missing_ok=True)
    return None


def stop_browser_use_session(log_dir: Path | str) -> bool:
    """Stop the active Browser Use session for the given runtime directory."""

    session = get_active_browser_use_session(log_dir)
    if session is None:
        return False

    try:
        os.killpg(session.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_running(session.pid):
            break
        time.sleep(0.1)

    if _is_process_running(session.pid):
        try:
            os.killpg(session.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    _active_session_path(log_dir).unlink(missing_ok=True)
    return True


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
    return _launch_browser_use_runner(
        normalized_url,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        agent_task=None,
    )


def open_apply_url_with_browser_use_candidate_agent(
    url: str,
    *,
    candidate_profile: CandidateProfile,
    log_dir: Path | str,
    startup_wait_seconds: float = STARTUP_WAIT_SECONDS,
) -> BrowserUseOpenResult:
    """Open an apply URL and start a Browser Use test agent with CV upload context."""

    normalized_url = _require_http_url(url)
    return _launch_browser_use_runner(
        normalized_url,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        agent_task=build_test_application_fill_task(
            normalized_url,
            candidate_profile,
        ),
    )


def build_test_application_fill_task(
    url: str,
    candidate_profile: CandidateProfile,
) -> str:
    """Return the guarded Browser Use task for test-filling with CV upload."""

    cv_file_path = candidate_profile.candidate_profile.source_documents.cv.file_path.strip()
    cv_instruction = (
        f'If the page asks for a CV upload, upload this file: "{cv_file_path}".'
        if cv_file_path
        else "No CV file path is available, so skip CV upload fields."
    )

    return f"""
Open this job application page and complete the visible application form for a test run:
{url}

Use only random, clearly fake test data for text fields and other non-file
inputs. Invent plausible values for required text fields, radio buttons,
checkboxes, dropdowns, and consent or acknowledgement controls that are
necessary to mark visible mandatory fields as complete.

CV upload instruction:
{cv_instruction}

Hard safety rules:
- Never click, press, or activate a button or link named "Weiter & Pruefen",
  "Weiter & Prüfen", "Absenden", "Senden", "Submit", "Apply", "Bewerbung absenden",
  or any equivalent button that would proceed to review, submit, or finalize the
  application.
- Stop when all visible mandatory fields are filled or marked, leaving the page
  ready for manual inspection.

Only upload the CV file when a resume or CV field is required. Do not upload any
other attachment. Do not create or upload a cover letter, portfolio, certificate,
or any other document. If a required field cannot be safely completed without
uploading another document, making a legal declaration, creating an account, or
proceeding with the application, leave it untouched and report that it is
blocked. Your final answer should summarize filled fields, uploaded files,
blocked fields, and whether the page is ready for human review.
""".strip()


def _launch_browser_use_runner(
    normalized_url: str,
    *,
    log_dir: Path | str,
    startup_wait_seconds: float,
    agent_task: str | None,
) -> BrowserUseOpenResult:
    target_log_dir = Path(log_dir)
    target_log_dir.mkdir(parents=True, exist_ok=True)
    existing_session = get_active_browser_use_session(target_log_dir)
    if existing_session is not None:
        raise BrowserUseLaunchError(
            "A Browser Use session is already running. Stop the active session before "
            "starting a new one."
        )
    log_path = target_log_dir / _build_log_filename(agent_task=agent_task is not None)
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
    if agent_task:
        command.extend(["--agent-task", agent_task])

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

    try:
        _wait_for_browser_ready(process, log_path, ready_path, startup_wait_seconds)
    except Exception:
        _active_session_path(target_log_dir).unlink(missing_ok=True)
        raise

    _write_active_session(
        target_log_dir,
        BrowserUseSession(
            url=normalized_url,
            pid=process.pid,
            log_path=log_path,
            started_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    return BrowserUseOpenResult(url=normalized_url, pid=process.pid, log_path=log_path)


def _require_http_url(url: str) -> str:
    normalized_url = url.strip()
    if not normalized_url:
        raise BrowserUseLaunchError("Enter a job URL before opening Browser Use.")

    parsed = urlsplit(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserUseLaunchError("Browser Use can only open a valid http or https URL.")
    return normalized_url


def _build_log_filename(*, agent_task: bool = False) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    purpose = "apply-agent" if agent_task else "job-intake"
    return f"browser-use-{purpose}-{timestamp}.log"


def _browser_use_environment(runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["BROWSER_USE_CONFIG_DIR"] = str(runtime_dir / "config")
    env["XDG_CACHE_HOME"] = str(runtime_dir / "cache")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "playwright-browsers")
    return env


def _active_session_path(log_dir: Path | str) -> Path:
    return Path(log_dir) / "active_session.json"


def _write_active_session(log_dir: Path | str, session: BrowserUseSession) -> None:
    session_path = _active_session_path(log_dir)
    session_path.write_text(
        json.dumps(
            {
                "url": session.url,
                "pid": session.pid,
                "log_path": str(session.log_path),
                "started_at": session.started_at,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
