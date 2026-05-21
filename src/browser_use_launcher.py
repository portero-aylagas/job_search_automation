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

from src.application_fill_plan import get_application_fill_plan_review_blockers
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
)

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


def open_apply_url_with_browser_use_fill_plan(
    url: str,
    *,
    fill_plan: ApplicationFillPlan,
    log_dir: Path | str,
    startup_wait_seconds: float = STARTUP_WAIT_SECONDS,
) -> BrowserUseOpenResult:
    """Open an apply URL and start a Browser Use agent from a reviewed fill plan."""

    normalized_url = _require_http_url(url)
    if fill_plan.review_status != "reviewed":
        raise BrowserUseLaunchError("Review the application fill plan before applying.")
    review_blockers = get_application_fill_plan_review_blockers(fill_plan)
    if review_blockers:
        raise BrowserUseLaunchError(" ".join(review_blockers))
    return _launch_browser_use_runner(
        normalized_url,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        agent_task=build_fill_plan_application_task(fill_plan),
        available_file_paths=_fill_plan_available_file_paths(fill_plan),
    )


def build_fill_plan_application_task(fill_plan: ApplicationFillPlan) -> str:
    """Return the guarded Browser Use task for a reviewed application fill plan."""

    execution_payload = {
        "review_status": fill_plan.review_status,
        "field_values": [
            _fill_plan_payload_item(field) for field in fill_plan.field_values
        ],
        "upload_files": [
            _fill_plan_payload_item(upload) for upload in fill_plan.upload_files
        ],
        "blocked_fields": [
            _fill_plan_payload_item(field) for field in fill_plan.blocked_fields
        ],
        "submit_guard_labels": fill_plan.submit_guard_labels,
    }
    payload = json.dumps(execution_payload, indent=2, ensure_ascii=True)

    return f"""
Use the job application page already open in the browser and execute only this
reviewed application fill plan.

Reviewed application fill plan:
{payload}

Before filling or uploading:
- Prefer matching controls by literal_evidence when literal_evidence is
  present. literal_evidence contains exact or near-exact text captured from the
  saved application_page_snapshot.json.
- Treat interpreted_label and label as semantic hints, not guaranteed live page
  text. When evidence_status is "interpreted_only" or literal_evidence is empty,
  do not assume that label text is present on the live page.
- Do not force actions against text or controls that are not present on the live
  page.
- Do not translate the page and do not switch the page language unless the form
  cannot be reached otherwise.
- Ignore browser translation prompts and site translation prompts. If they block
  the page, close or dismiss them instead of accepting translation.
- If a cookie, privacy, newsletter, chat, location, notification, or modal
  overlay blocks the upload control, dismiss it with the least intrusive
  option that lets you continue. Prefer reject, necessary-only, close, or later
  over broad marketing consent when those choices are available.
- Wait for the page to settle after any redirect or popup dismissal before
  looking for upload controls or fillable fields.

Hard safety rules:
- Fill only fields listed in field_values.
- If a listed field has an empty value and required is false, treat it as an
  intentionally reviewed blank value. Leave that matching control blank or
  unchecked, and report it as intentionally blank.
- For checkbox fields, value "true" means check/confirm the matching control
  and value "false" means leave it unchecked or uncheck it if needed.
- For checkbox_group or multiselect fields, split reviewed values on semicolons
  when semicolons are present; otherwise treat the whole value as one exact
  option label.
- Upload only files listed in upload_files, using Browser Use's upload_file
  action directly on matching upload controls.
- Never click upload controls to open the operating-system file picker.
- Never type or paste the CV file path, or any other file path, into any page
  field or file picker.
- Never touch fields listed in blocked_fields.
- Leave sensitive fields such as disability, referral, internal employee status,
  optional group sharing, and optional consent/marketing choices untouched
  unless they are explicitly listed in field_values.
- Do not fill, select, type into, click, or modify any field that is not listed
  in field_values or upload_files.
- Never click, press, or activate a button or link named "Weiter & Pruefen",
  "Weiter & Prüfen", "Absenden", "Senden", "Submit", "Apply", "Bewerbung absenden",
  or any label from submit_guard_labels.
- If upload_file reports an error or says the file is not available, stop
  immediately and report the upload as failed.
- Stop after all fill-plan actions are completed or blocked. Leave the page
  ready for manual inspection.

Your final answer should summarize filled fields, uploaded files, blocked
fields, failed actions, and whether the page is ready for human review.
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


def _fill_plan_available_file_paths(fill_plan: ApplicationFillPlan) -> list[Path]:
    return [Path(upload.file_path) for upload in fill_plan.upload_files if upload.file_path]


def _fill_plan_payload_item(
    item: ApplicationFillFieldValue | ApplicationFillUploadFile | ApplicationFillBlockedField,
) -> dict[str, object]:
    payload = item.model_dump(mode="json")
    payload["interpreted_label"] = item.label
    return payload


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
