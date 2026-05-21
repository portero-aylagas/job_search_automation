from __future__ import annotations

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
    stop_browser_use_session,
)
from src.schemas import CandidateProfile


class FakeRunningProcess:
    pid = 12345

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: int) -> None:
        return None


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
    assert "random, clearly fake test data" in agent_task
    assert "/tmp/candidate/cv.pdf" in agent_task
    assert "Weiter & Prüfen" in agent_task
    assert "Only upload the CV file" in agent_task
    assert result.log_path.name.startswith("browser-use-apply-agent-")


def test_build_test_application_fill_task_contains_cv_upload_and_submit_guard() -> None:
    task = build_test_application_fill_task(
        "https://example.com/apply",
        make_profile(),
    )

    assert "random, clearly fake test data" in task
    assert 'upload this file: "/tmp/candidate/cv.pdf"' in task
    assert "Never click" in task
    assert "Weiter & Prüfen" in task
    assert "Absenden" in task
    assert "Only upload the CV file" in task
    assert "reviewed candidate data" not in task


def test_open_url_with_browser_use_rejects_second_active_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeRunningProcess())
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    open_url_with_browser_use(
        "https://example.com/jobs/automation-engineer",
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    with pytest.raises(BrowserUseLaunchError, match="already running"):
        open_url_with_browser_use(
            "https://example.com/jobs/second-role",
            log_dir=tmp_path,
            startup_wait_seconds=0,
        )


def test_stop_browser_use_session_terminates_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeRunningProcess())
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
