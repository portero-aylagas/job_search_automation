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


def stop_all_browser_use_processes(log_dir: Path | str) -> int:
    """Stop all Browser Use runner processes started by this project."""

    stopped_count = 0
    if stop_browser_use_session(log_dir):
        stopped_count += 1

    for pid, pgid in _find_browser_use_runner_processes():
        if not _is_process_running(pid):
            continue
        if _terminate_process_group(pgid):
            stopped_count += 1

    _active_session_path(log_dir).unlink(missing_ok=True)
    return stopped_count


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
    """Open an apply URL and start a Browser Use agent for a small upload test."""

    normalized_url = _require_http_url(url)
    return _launch_browser_use_runner(
        normalized_url,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        agent_task=build_test_application_fill_task(
            normalized_url,
            candidate_profile,
        ),
        available_file_paths=_candidate_available_file_paths(candidate_profile),
    )


def build_test_application_fill_task(
    url: str,
    candidate_profile: CandidateProfile,
) -> str:
    """Return the guarded Browser Use task for CV upload and one probe field."""

    cv_file_path = candidate_profile.candidate_profile.source_documents.cv.file_path.strip()
    cv_instruction = (
        f'Upload this CV file if a resume or CV upload control is available: "{cv_file_path}".'
        if cv_file_path
        else "No CV file path is available, so do not upload any file."
    )

    return f"""
Use the job application page already open in the browser for a small apply-form
test.

Perform the actions in this order:
1. Find a file upload control that clearly requests a CV, resume, or Lebenslauf.
2. Upload the CV using Browser Use's upload_file action only.
3. After the upload action has completed, find the field labelled "Vorname *"
   and enter exactly "TestName".

Do not fill any other text field. Do not select radio buttons, checkboxes,
dropdowns, or consent controls. Do not enter random data. This run is only for
testing whether the agent can visibly fill one field and upload the CV.

Before uploading:
- Do not translate the page and do not switch the page language unless the form
  cannot be reached otherwise.
- Ignore browser translation prompts and site translation prompts. If they block
  the page, close or dismiss them instead of accepting translation.
- If a cookie, privacy, newsletter, chat, location, notification, or modal
  overlay blocks the upload control, dismiss it with the least intrusive
  option that lets you continue. Prefer reject, necessary-only, close, or later
  over broad marketing consent when those choices are available.
- Wait for the page to settle after any redirect or popup dismissal before
  looking for upload controls.

CV upload instruction:
{cv_instruction}

Hard safety rules:
- The only non-file form field you may type into is "Vorname *", and its value
  must be exactly "TestName".
- Only interact with upload controls that clearly request a CV, resume, or
  Lebenslauf.
- Do not click the upload control to open the operating-system file picker. Use
  the upload_file action directly on the upload control.
- Never type or paste the CV file path into any page field or file picker.
- Do not upload cover letters, portfolios, certificates, photos, or any other
  attachments.
- Do not type into or modify any other non-file form field.
- Never click, press, or activate a button or link named "Weiter & Pruefen",
  "Weiter & Prüfen", "Absenden", "Senden", "Submit", "Apply", "Bewerbung absenden",
  or any equivalent button that would proceed to review, submit, or finalize the
  application.
- Stop after "Vorname *" is set to "TestName" and the CV is uploaded, or after
  you determine that either target action is blocked. Leave the page ready for
  manual inspection.

If upload_file reports an error or says the file is not available, stop
immediately and report the upload as failed. Do not retry by clicking the upload
control, opening the file picker, typing the path, or claiming success.

Your final answer should summarize whether "Vorname *" was filled, whether the
CV was uploaded, which upload control was used, and whether anything blocked the
test.
""".strip()


def _launch_browser_use_runner(
    normalized_url: str,
    *,
    log_dir: Path | str,
    startup_wait_seconds: float,
    agent_task: str | None,
    available_file_paths: list[Path] | None = None,
) -> BrowserUseOpenResult:
    target_log_dir = Path(log_dir)
    target_log_dir.mkdir(parents=True, exist_ok=True)
    stop_all_browser_use_processes(target_log_dir)
    existing_session = get_active_browser_use_session(target_log_dir)
    if existing_session is not None:
        raise BrowserUseLaunchError(
            "A Browser Use session is already running. Stop the active session before "
            "starting a new one."
        )
    log_path = target_log_dir / _build_log_filename(agent_task=agent_task is not None)
    ready_path = log_path.with_suffix(".ready")
    user_data_dir = target_log_dir / "sessions" / log_path.stem
    browser_use_env = _browser_use_environment(target_log_dir)
    repo_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "src.browser_use_visible_runner",
        normalized_url,
        "--ready-file",
        str(ready_path),
        "--user-data-dir",
        str(user_data_dir),
    ]
    if agent_task:
        command.extend(["--agent-task", agent_task])
    for file_path in available_file_paths or []:
        command.extend(["--available-file-path", str(file_path)])

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


def _candidate_available_file_paths(candidate_profile: CandidateProfile) -> list[Path]:
    cv_file_path = candidate_profile.candidate_profile.source_documents.cv.file_path.strip()
    if not cv_file_path:
        return []
    return [Path(cv_file_path)]


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


def _terminate_process_group(pgid: int) -> bool:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_running(pgid):
            return True
        time.sleep(0.1)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return True


def _find_browser_use_runner_processes() -> list[tuple[int, int]]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,pgid=,args="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    current_pid = os.getpid()
    matches: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            pgid = int(parts[1])
        except ValueError:
            continue
        args = parts[2]
        if pid == current_pid:
            continue
        if "src.browser_use_visible_runner" in args:
            matches.append((pid, pgid))
    return matches


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
