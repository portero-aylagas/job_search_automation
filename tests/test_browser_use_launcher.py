from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.browser_use_launcher import (
    BrowserUseLaunchError,
    build_candidate_application_fill_task,
    open_apply_url_with_browser_use_candidate_agent,
    open_url_with_browser_use,
)
from src.schemas import ApplicationPackage, CandidateProfile


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

    result = open_apply_url_with_browser_use_candidate_agent(
        "https://example.com/apply/automation-engineer",
        candidate_profile=make_profile(),
        application_package=make_package(),
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--agent-task" in command
    agent_task = command[command.index("--agent-task") + 1]
    assert "Taylor Rivera" in agent_task
    assert "Automation Engineer" in agent_task
    assert "Weiter & Prüfen" in agent_task
    assert "Anhang hochladen" in agent_task
    assert "Do not upload files or attachments." in agent_task
    assert result.log_path.name.startswith("browser-use-apply-agent-")


def test_build_candidate_application_fill_task_contains_candidate_data_and_submit_guard() -> None:
    task = build_candidate_application_fill_task(
        "https://example.com/apply",
        make_profile(),
        make_package(),
    )

    assert "reviewed candidate data" in task
    assert "Taylor Rivera" in task
    assert "taylor@example.com" in task
    assert "Python, Playwright" in task
    assert "Screening Answer 1" in task
    assert "I am interested in this role because" in task
    assert "Never click" in task
    assert "Weiter & Prüfen" in task
    assert "Absenden" in task
    assert "Anhang hochladen" in task
    assert "random, clearly fake test data" not in task


def make_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
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


def make_package() -> ApplicationPackage:
    return ApplicationPackage.model_validate(
        {
            "job_id": "example-co-automation-engineer",
            "artifacts": [
                {
                    "id": "screening-question-1",
                    "type": "form_answer",
                    "label": "Screening Answer 1",
                    "status": "draft",
                    "content": (
                        "I am interested in this role because it matches my "
                        "automation experience."
                    ),
                }
            ],
        }
    )
