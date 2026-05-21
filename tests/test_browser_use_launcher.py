from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from src.browser_use_launcher import (
    BrowserUseLaunchError,
    build_test_application_fill_task,
    get_active_browser_use_session,
    open_apply_url_with_browser_use_candidate_agent,
    open_url_with_browser_use,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.browser_use_visible_runner import _close_existing_pages, _write_stable_profile_preferences
from src.schemas import CandidateProfile


class FakeRunningProcess:
    pid = 12345

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: int) -> None:
        return None


def no_stale_processes(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="")


def test_open_url_with_browser_use_rejects_blank_url(tmp_path: Path) -> None:
    with pytest.raises(BrowserUseLaunchError, match="Enter a job URL"):
        open_url_with_browser_use(" ", log_dir=tmp_path, startup_wait_seconds=0)


def test_open_url_with_browser_use_rejects_non_http_url(tmp_path: Path) -> None:
    with pytest.raises(BrowserUseLaunchError, match="http or https"):
        open_url_with_browser_use("mailto:jobs@example.com", log_dir=tmp_path)


def test_open_url_with_browser_use_starts_visible_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(
        command: list[str],
        *,
        cwd: Path,
        stdout: object,
        stderr: int,
        text: bool,
        start_new_session: bool,
        env: dict[str, str],
    ) -> FakeRunningProcess:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stderr"] = stderr
        captured["text"] = text
        captured["start_new_session"] = start_new_session
        captured["env"] = env
        return FakeRunningProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", no_stale_processes)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    result = open_url_with_browser_use(
        "https://example.com/jobs/automation-engineer",
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1:4] == [
        "-m",
        "src.browser_use_visible_runner",
        "https://example.com/jobs/automation-engineer",
    ]
    assert command[4] == "--ready-file"
    assert command[5].endswith(".ready")
    assert command[6] == "--user-data-dir"
    assert "sessions/browser-use-job-intake-" in command[7]
    assert captured["start_new_session"] is True
    assert captured["text"] is True
    assert captured["stderr"] == subprocess.STDOUT
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["BROWSER_USE_CONFIG_DIR"] == str(tmp_path / "config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache")
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "playwright-browsers")
    assert result.pid == 12345
    assert result.log_path.parent == tmp_path
    session = get_active_browser_use_session(tmp_path)
    assert session is not None
    assert session.pid == 12345
    assert session.url == "https://example.com/jobs/automation-engineer"


def test_open_apply_url_with_browser_use_candidate_agent_passes_guarded_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(
        command: list[str],
        *,
        cwd: Path,
        stdout: object,
        stderr: int,
        text: bool,
        start_new_session: bool,
        env: dict[str, str],
    ) -> FakeRunningProcess:
        captured["command"] = command
        return FakeRunningProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", no_stale_processes)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    result = open_apply_url_with_browser_use_candidate_agent(
        "https://example.com/apply/automation-engineer",
        candidate_profile=make_profile(),
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--agent-task" in command
    agent_task = command[command.index("--agent-task") + 1]
    assert "small apply-form test" in agent_task
    assert 'field labelled "Vorname *"' in agent_task
    assert 'enter exactly "TestName"' in agent_task
    assert "Do not enter random data" in agent_task
    assert "/tmp/candidate/cv.pdf" in agent_task
    assert "Do not translate the page" in agent_task
    assert "translation prompts" in agent_task
    assert "cookie, privacy, newsletter, chat" in agent_task
    assert "Weiter & Prüfen" in agent_task
    assert "Only interact with upload controls" in agent_task
    assert result.log_path.name.startswith("browser-use-apply-agent-")


def test_build_test_application_fill_task_contains_probe_field_cv_and_submit_guard() -> None:
    task = build_test_application_fill_task(
        "https://example.com/apply",
        make_profile(),
    )

    assert "small apply-form test" in task
    assert 'field labelled "Vorname *"' in task
    assert 'enter exactly "TestName"' in task
    assert 'only non-file form field you may type into is "Vorname *"' in task
    assert "Do not enter random data" in task
    assert 'Upload this CV file' in task
    assert '"/tmp/candidate/cv.pdf"' in task
    assert "Do not translate the page" in task
    assert "dismiss them instead of accepting translation" in task
    assert "least intrusive" in task
    assert "Never click" in task
    assert "Weiter & Prüfen" in task
    assert "Absenden" in task
    assert "Only interact with upload controls" in task
    assert "Do not type into or modify any other non-file form field" in task
    assert "Do not upload cover letters" in task
    assert "reviewed candidate data" not in task
    assert "random, clearly fake test data" not in task


def test_open_url_with_browser_use_starts_fresh_when_session_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launches: list[object] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeRunningProcess:
        launches.append(args)
        return FakeRunningProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", no_stale_processes)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)

    open_url_with_browser_use(
        "https://example.com/jobs/automation-engineer",
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    result = open_url_with_browser_use(
        "https://example.com/jobs/second-role",
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    assert len(launches) == 2
    assert result.url == "https://example.com/jobs/second-role"


def test_stop_browser_use_session_terminates_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeRunningProcess())
    monkeypatch.setattr(subprocess, "run", no_stale_processes)
    open_url_with_browser_use(
        "https://example.com/jobs/automation-engineer",
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    signals_sent: list[tuple[int, int]] = []
    running_state = {"alive": True}

    def fake_killpg(pid: int, sig: int) -> None:
        signals_sent.append((pid, sig))
        if sig != 0:
            running_state["alive"] = False

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0 and running_state["alive"]:
            return
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", fake_killpg)
    monkeypatch.setattr(os, "kill", fake_kill)

    assert stop_browser_use_session(tmp_path) is True
    assert signals_sent
    assert get_active_browser_use_session(tmp_path) is None


def test_stop_all_browser_use_processes_finds_stale_runners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "111 111 python -m src.browser_use_visible_runner https://example.com\n"
                "222 222 python -m unrelated.module\n"
            ),
        ),
    )

    running_pids = {111}
    killed_groups: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0 and pid in running_pids:
            return
        if sig == 0:
            raise ProcessLookupError

    def fake_killpg(pgid: int, sig: int) -> None:
        killed_groups.append((pgid, sig))
        running_pids.discard(pgid)

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(os, "killpg", fake_killpg)

    assert stop_all_browser_use_processes(tmp_path) == 1
    assert killed_groups


def test_stable_profile_preferences_disable_translate(tmp_path: Path) -> None:
    user_data_dir = tmp_path / "browser-profile"

    _write_stable_profile_preferences(user_data_dir)

    preferences = (user_data_dir / "Default" / "Preferences").read_text(encoding="utf-8")
    local_state = (user_data_dir / "Local State").read_text(encoding="utf-8")
    assert '"translate"' in preferences
    assert '"enabled": false' in preferences
    assert '"notifications": 2' in preferences
    assert '"app_locale": "en-US"' in local_state


def test_close_existing_pages_closes_tabs_before_navigation() -> None:
    class FakeBrowser:
        def __init__(self) -> None:
            self.closed_pages: list[str] = []

        async def get_pages(self) -> list[str]:
            return ["about:blank", "old-job"]

        async def close_page(self, page: str) -> None:
            self.closed_pages.append(page)

    browser = FakeBrowser()

    closed_count = asyncio.run(_close_existing_pages(browser))

    assert closed_count == 2
    assert browser.closed_pages == ["about:blank", "old-job"]


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {
                        "file_path": "/tmp/candidate/cv.pdf",
                        "parsed": True,
                    }
                },
                "cv_extracted": {
                    "identity": {
                        "full_name": "Taylor Rivera",
                        "email": "taylor@example.com",
                        "phone": "+49 123 456789",
                        "location": "Berlin, Germany",
                        "linkedin_url": "https://linkedin.com/in/taylor-rivera",
                    },
                    "skills": ["Python", "Playwright"],
                    "languages": ["English", "German"],
                    "work_experience": ["Automation Engineer at Example Co"],
                    "education": ["BSc Computer Science"],
                },
                "candidate_preferences": {
                    "target_roles": ["Automation Engineer"],
                    "target_locations": ["Berlin", "Remote"],
                    "remote_preference": ["remote"],
                    "employment_type": ["full_time"],
                    "seniority_level": ["mid_level"],
                    "availability": "Immediately",
                    "salary_min_eur": 65000,
                    "salary_max_eur": 80000,
                    "work_authorization": "eu_authorized",
                },
            }
        }
    )
