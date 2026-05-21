from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.browser_use_launcher import BrowserUseLaunchError, open_url_with_browser_use


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
