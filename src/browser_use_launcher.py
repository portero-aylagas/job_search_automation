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

from src.schemas import ApplicationPackage, CandidateProfile

STARTUP_WAIT_SECONDS = 30.0
STARTUP_POLL_SECONDS = 0.25
SETUP_REFERENCE = "Refer to README.md -> Installation -> Browser Use Setup."


@dataclass(frozen=True)
class BrowserUseOpenResult:
    """Result returned after starting a visible Browser Use session or task."""

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
    application_package: ApplicationPackage,
    log_dir: Path | str,
    startup_wait_seconds: float = STARTUP_WAIT_SECONDS,
) -> BrowserUseOpenResult:
    """Open an apply URL and start a Browser Use agent with candidate data."""

    normalized_url = _require_http_url(url)
    return _launch_browser_use_runner(
        normalized_url,
        log_dir=log_dir,
        startup_wait_seconds=startup_wait_seconds,
        agent_task=build_candidate_application_fill_task(
            normalized_url,
            candidate_profile,
            application_package,
        ),
    )


def build_candidate_application_fill_task(
    url: str,
    candidate_profile: CandidateProfile,
    application_package: ApplicationPackage,
) -> str:
    """Return the guarded Browser Use task for filling with reviewed candidate data."""

    candidate_summary = _format_candidate_summary(candidate_profile)
    package_summary = _format_package_summary(application_package)

    return f"""
Open this job application page and complete the visible application form using the
reviewed candidate data below:
{url}

Candidate profile:
{candidate_summary}

Application package:
{package_summary}

Use the reviewed candidate profile and application package as the source of truth.
Fill visible required text fields, radio buttons, checkboxes, dropdowns, and
consent or acknowledgement controls when the answer is supported by the candidate
data above. Reuse the package wording for screening answers when it matches the
field being filled.

Hard safety rules:
- Never click, press, or activate a button or link named "Weiter & Pruefen",
  "Weiter & Prüfen", "Absenden", "Senden", "Submit", "Apply", "Bewerbung absenden",
  or any equivalent button that would proceed to review, submit, or finalize the
  application.
- Do not upload files or attachments.
- Do not click "Anhang hochladen" and do not interact with any file upload
  control.
- Stop when all visible mandatory fields are filled or marked, leaving the page
  ready for manual inspection.

If a required field is missing from the candidate data, use a short neutral
placeholder only when it is necessary to complete a harmless form field and does
not invent a sensitive credential, legal declaration, or upload. If a required
field cannot be safely completed without uploading an attachment, making a legal
declaration, creating an account, or proceeding with the application, leave it
untouched and report that it is blocked. Your final answer should summarize
filled fields, skipped upload fields, blocked fields, and whether the page is
ready for human review.
""".strip()


def _format_candidate_summary(candidate_profile: CandidateProfile) -> str:
    identity = candidate_profile.candidate_profile.cv_extracted.identity
    preferences = candidate_profile.candidate_profile.candidate_preferences
    extracted = candidate_profile.candidate_profile.cv_extracted

    summary_lines = [
        f"- Full name: {_fallback_text(identity.full_name)}",
        f"- Email: {_fallback_text(identity.email)}",
        f"- Phone: {_fallback_text(identity.phone)}",
        f"- Location: {_fallback_text(identity.location)}",
        f"- LinkedIn: {_fallback_text(identity.linkedin_url)}",
        f"- GitHub: {_fallback_text(identity.github_url)}",
        f"- Portfolio: {_fallback_text(identity.portfolio_url)}",
        f"- Target roles: {_join_values(preferences.target_roles)}",
        f"- Target locations: {_join_values(preferences.target_locations)}",
        f"- Remote preference: {_join_values(preferences.remote_preference)}",
        f"- Employment type: {_join_values(preferences.employment_type)}",
        f"- Seniority level: {_join_values(preferences.seniority_level)}",
        f"- Availability: {_fallback_text(preferences.availability)}",
        (
            "- Salary expectation (EUR): "
            f"{_format_salary_range(preferences.salary_min_eur, preferences.salary_max_eur)}"
        ),
        f"- Work authorization: {_fallback_text(preferences.work_authorization)}",
        f"- Skills: {_join_values(extracted.skills)}",
        f"- Languages: {_join_values(extracted.languages)}",
        f"- Work experience: {_join_values(extracted.work_experience)}",
        f"- Education: {_join_values(extracted.education)}",
        f"- Certifications: {_join_values(extracted.certifications)}",
        f"- Projects: {_join_values(extracted.projects)}",
    ]
    return "\n".join(summary_lines)


def _format_package_summary(application_package: ApplicationPackage) -> str:
    if not application_package.artifacts:
        return "- No generated artifacts are available."

    artifact_blocks: list[str] = []
    for artifact in application_package.artifacts:
        content = " ".join(artifact.content.split())
        if len(content) > 600:
            content = f"{content[:597]}..."
        artifact_blocks.append(
            "\n".join(
                [
                    f"- {artifact.label} ({artifact.type}, status={artifact.status}):",
                    content or "_No content generated._",
                ]
            )
        )
    return "\n".join(artifact_blocks)


def _join_values(values: list[object]) -> str:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(normalized) if normalized else "Not provided"


def _fallback_text(value: str) -> str:
    normalized = value.strip()
    return normalized or "Not provided"


def _format_salary_range(min_salary: int | None, max_salary: int | None) -> str:
    if min_salary is None and max_salary is None:
        return "Not provided"
    if min_salary is None:
        return f"Up to {max_salary}"
    if max_salary is None:
        return f"From {min_salary}"
    return f"{min_salary} to {max_salary}"


def _launch_browser_use_runner(
    normalized_url: str,
    *,
    log_dir: Path | str,
    startup_wait_seconds: float,
    agent_task: str | None,
) -> BrowserUseOpenResult:
    target_log_dir = Path(log_dir)
    target_log_dir.mkdir(parents=True, exist_ok=True)
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
