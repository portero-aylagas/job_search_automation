from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.browser_use_launcher import (
    BrowserUseLaunchError,
    build_fill_plan_application_task,
    get_active_browser_use_session,
    open_apply_url_with_browser_use_fill_plan,
    open_url_with_browser_use,
    stop_all_browser_use_processes,
    stop_browser_use_session,
)
from src.browser_use_visible_runner import (
    _browser_use_agent_max_steps,
    _build_traced_browser_use_chat_model,
    _close_existing_pages,
    _close_other_pages,
    _open_page_with_retries,
    _page_has_interactive_content,
    _run_browser_use_apply_agent,
    _write_stable_profile_preferences,
)
from src.schemas import (
    ApplicationFillBlockedField,
    ApplicationFillFieldValue,
    ApplicationFillNeedsAnswerField,
    ApplicationFillPlan,
    ApplicationFillUploadFile,
)


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


def extract_task_payload(task: str) -> dict[str, object]:
    payload_text = task.split("Reviewed application fill plan:\n", maxsplit=1)[1]
    payload_text = payload_text.split("\n\nThe JSON is split by action intent:", maxsplit=1)[0]
    return json.loads(payload_text)


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


def test_open_apply_url_with_browser_use_fill_plan_passes_guarded_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    cv_path = tmp_path / "candidate" / "cv.pdf"
    cv_path.parent.mkdir(parents=True)
    cv_path.write_bytes(b"%PDF cv")

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

    result = open_apply_url_with_browser_use_fill_plan(
        "https://example.com/apply/automation-engineer",
        fill_plan=make_fill_plan(str(cv_path)),
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--agent-task" in command
    assert "--require-interactive-page" in command
    assert "--page-ready-timeout-seconds" in command
    assert command[command.index("--page-ready-timeout-seconds") + 1] == "60.0"
    assert "--available-file-path" in command
    assert command[command.index("--available-file-path") + 1] == str(cv_path)
    agent_task = command[command.index("--agent-task") + 1]
    assert "reviewed application fill plan" in agent_task
    assert "https://example.com/apply/automation-engineer" not in agent_task
    assert '"field_values_before_upload"' in agent_task
    assert '"mandatory_checkbox_fields"' in agent_task
    assert '"intentionally_blank_fields"' in agent_task
    assert '"intentionally_untouched_checkbox_fields"' in agent_task
    assert '"upload_files_last"' in agent_task
    assert '"blocked_fields"' in agent_task
    assert '"accept_terms_and_privacy"' not in agent_task
    assert '"interpreted_label": "Vorname"' in agent_task
    assert '"literal_evidence": [' in agent_task
    assert '"consent_privacy_gate_fields"' not in agent_task
    assert '"value": "Taylor"' in agent_task
    assert '"value": "true"' in agent_task
    assert '"label": "Lebenslauf"' in agent_task
    assert str(cv_path) in agent_task
    assert "Do not translate the page" in agent_task
    assert "translation prompts" in agent_task
    assert "cookie, privacy, newsletter, chat" in agent_task
    assert "Weiter & Prüfen" in agent_task
    assert "using Browser Use's upload_file" in agent_task
    assert "Never click upload controls" in agent_task
    assert "Never type or paste the CV file path" in agent_task
    assert "Never touch fields listed in blocked_fields" in agent_task
    assert "accept_terms_and_privacy is true" not in agent_task
    assert "consent_privacy_gate_fields" not in agent_task
    assert "semantic hints" in agent_task
    assert "guaranteed live page" in agent_task
    assert "evidence_status is \"interpreted_only\"" in agent_task
    assert "reviewed blank values" in agent_task
    assert "Never click checkbox controls listed" in agent_task
    assert "Process every item in mandatory_checkbox_fields" in agent_task
    assert "mandatory_checkbox_fields exactly once" in agent_task
    assert "never click it again" in agent_task
    assert "Upload completion is not task completion" in agent_task
    assert "checked mandatory checkboxes" in agent_task
    assert "First, process every item in field_values_before_upload" in agent_task
    assert "optional non-empty fields such as telephone" in agent_task
    assert "Last, and only after all field_values_before_upload" in agent_task
    assert (
        "mandatory_checkbox_fields rows are complete or explicitly reported as failed"
        in agent_task
    )
    assert "never navigate, reload, or open a new tab" in agent_task
    assert "ATS gate" not in agent_task
    assert "candidate_profile" not in agent_task
    assert "cv_extracted" not in agent_task
    assert result.log_path.name.startswith("browser-use-apply-agent-")


def test_open_apply_url_passes_and_serializes_multiple_upload_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    cv_path = tmp_path / "candidate" / "cv.pdf"
    cover_letter_path = tmp_path / "generated" / "cover_letter.pdf"
    cv_path.parent.mkdir(parents=True)
    cover_letter_path.parent.mkdir(parents=True)
    cv_path.write_bytes(b"%PDF cv")
    cover_letter_path.write_bytes(b"%PDF cover")

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

    fill_plan = make_fill_plan(str(cv_path))
    fill_plan.source_metadata["package_upload_artifacts"] = [
        {"generated_file_path": str(cover_letter_path), "downloaded_file_path": ""}
    ]
    fill_plan.upload_files.append(
        ApplicationFillUploadFile(
            label="Cover letter",
            file_path=str(cover_letter_path),
            document_type="cover_letter",
            required=True,
            source="manual_review",
            confidence="high",
        )
    )

    open_apply_url_with_browser_use_fill_plan(
        "https://example.com/apply/automation-engineer",
        fill_plan=fill_plan,
        log_dir=tmp_path,
        startup_wait_seconds=0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    upload_flag_indexes = [
        index for index, value in enumerate(command) if value == "--available-file-path"
    ]
    assert [command[index + 1] for index in upload_flag_indexes] == [
        str(cv_path),
        str(cover_letter_path),
    ]
    agent_task = command[command.index("--agent-task") + 1]
    assert '"label": "Lebenslauf"' in agent_task
    assert '"label": "Cover letter"' in agent_task
    assert json.dumps(str(cv_path)) in agent_task
    assert json.dumps(str(cover_letter_path)) in agent_task


def test_build_fill_plan_application_task_contains_reviewed_contract_only() -> None:
    task = build_fill_plan_application_task(make_fill_plan())

    assert "reviewed application fill plan" in task
    assert '"field_values_before_upload"' in task
    assert '"mandatory_checkbox_fields"' in task
    assert '"intentionally_blank_fields"' in task
    assert '"intentionally_untouched_checkbox_fields"' in task
    assert '"upload_files_last"' in task
    assert '"blocked_fields"' in task
    assert '"accept_terms_and_privacy"' not in task
    assert '"interpreted_label": "Vorname"' in task
    assert '"literal_evidence": [' in task
    assert '"consent_privacy_gate_fields"' not in task
    assert '"label": "Vorname"' in task
    assert '"value": "Taylor"' in task
    assert '"label": "Privacy acknowledgement"' in task
    assert '"value": "true"' in task
    assert '"label": "Internal application"' in task
    assert "ATS gate" not in task
    assert "Upload only files listed in upload_files_last" in task
    assert '"/tmp/candidate/cv.pdf"' in task
    assert "Do not translate the page" in task
    assert "dismiss them instead of accepting translation" in task
    assert "least intrusive" in task
    assert "Never click" in task
    assert "Weiter & Prüfen" in task
    assert "Absenden" in task
    assert "Never touch fields listed in blocked_fields" in task
    assert "accept_terms_and_privacy is true" not in task
    assert "semantic hints" in task
    assert "guaranteed live page" in task
    assert "Do not force actions against text or controls" in task
    assert "Never click upload controls" in task
    assert "Never type or paste the CV file path" in task
    assert "Do not fill, select, type into, click, or modify any field" in task
    assert "reviewed blank values" in task
    assert "split reviewed values on semicolons" in task
    assert "A sensitive or consent checkbox with value \"true\"" in task
    assert "Process every item in mandatory_checkbox_fields" in task
    assert "Upload completion is not task completion" in task
    assert "Do not mark a field complete from memory" in task
    assert "mandatory_checkbox_fields exactly once" in task
    assert "never click it again" in task
    assert "verify live field values and checkbox states before any upload" not in task
    assert "Merely\n  extracting labels is not verification" not in task
    assert "Never start file uploads before every field_values_before_upload row" in task
    assert (
        "every mandatory_checkbox_fields\n  row is complete or explicitly reported as failed"
        in task
    )
    assert "If upload_file reports an error" in task
    assert "Upload each listed file_path at most one time" in task
    assert "Do not restart the upload list" in task
    assert "do not search for additional\n  required checkboxes" in task
    assert "candidate_profile" not in task
    assert "cv_extracted" not in task


def test_build_fill_plan_application_task_highlights_true_checkboxes_only() -> None:
    task = build_fill_plan_application_task(make_fill_plan())

    mandatory_section = task.split('"mandatory_checkbox_fields"', maxsplit=1)[1]
    mandatory_section = mandatory_section.split('"intentionally_blank_fields"', maxsplit=1)[0]

    assert '"label": "Privacy acknowledgement"' in mandatory_section
    assert '"value": "true"' in mandatory_section
    assert '"label": "Vorname"' not in mandatory_section
    assert '"value": "false"' not in mandatory_section
    assert "ATS gate" not in mandatory_section


def test_build_fill_plan_application_task_keeps_false_checkboxes_report_only() -> None:
    task_payload = extract_task_payload(build_fill_plan_application_task(make_fill_plan()))

    field_labels = [
        str(field["label"]) for field in task_payload["field_values_before_upload"]
    ]
    mandatory_labels = [
        str(field["label"]) for field in task_payload["mandatory_checkbox_fields"]
    ]
    untouched_labels = [
        str(field["label"])
        for field in task_payload["intentionally_untouched_checkbox_fields"]
    ]
    blank_labels = [
        str(field["label"]) for field in task_payload["intentionally_blank_fields"]
    ]

    assert field_labels == ["Vorname"]
    assert mandatory_labels == ["Privacy acknowledgement"]
    assert untouched_labels == ["Internal application"]
    assert blank_labels == ["Employee referral"]
    assert all("ATS gate" not in label for label in field_labels)
    assert all("ATS gate" not in label for label in mandatory_labels)
    assert all("ATS gate" not in label for label in untouched_labels)


def test_build_fill_plan_application_task_dedupes_repeated_action_targets() -> None:
    fill_plan = make_fill_plan()
    fill_plan.field_values.extend(
        [
            ApplicationFillFieldValue(
                label="Privacy gate before continuing",
                value="true",
                required=True,
                input_type="checkbox",
                options=["true", "false"],
                source="manual_review",
                confidence="high",
                literal_evidence=["Privacy acknowledgement"],
                evidence_source="form_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="Standorte, die fuer Sie in Frage kommen",
                name="job_application_start_form[location_names][]",
                value="Munich",
                required=True,
                input_type="checkbox_group",
                options=["Munich", "Berlin"],
                source="application_package.form_answer",
                confidence="medium",
                literal_evidence=["job_application_start_form[location_names][]"],
                evidence_source="control_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="Bitte waehlen Sie alle Standorte aus",
                value="Munich",
                required=True,
                input_type="checkbox_group",
                options=[],
                source="application_package.form_answer",
                confidence="medium",
                literal_evidence=["Position is available in Munich and Berlin"],
                evidence_source="visible_text_excerpt",
                evidence_status="partial_match",
            ),
        ]
    )
    fill_plan.upload_files.append(
        ApplicationFillUploadFile(
            label="Duplicate CV",
            file_path="/tmp/candidate/cv.pdf",
            document_type="cv",
            required=True,
            source="manual_review",
            confidence="high",
        )
    )

    task_payload = extract_task_payload(build_fill_plan_application_task(fill_plan))

    field_labels = [
        str(field["label"]) for field in task_payload["field_values_before_upload"]
    ]
    mandatory_labels = [
        str(field["label"]) for field in task_payload["mandatory_checkbox_fields"]
    ]
    upload_paths = [
        str(upload["file_path"]) for upload in task_payload["upload_files_last"]
    ]

    assert field_labels == ["Vorname", "Standorte, die fuer Sie in Frage kommen"]
    assert mandatory_labels == ["Privacy acknowledgement"]
    assert upload_paths == ["/tmp/candidate/cv.pdf"]


def test_build_fill_plan_application_task_keeps_uploads_last() -> None:
    task = build_fill_plan_application_task(make_fill_plan())

    assert task.index('"field_values_before_upload"') < task.index('"upload_files_last"')
    assert task.index("First, process every item in field_values_before_upload") < task.index(
        "mandatory_checkbox_fields exactly once"
    )
    assert task.index("mandatory_checkbox_fields exactly once") < task.index(
        "Last, and only after all field_values_before_upload"
    )
    assert task.index("First, process every item in field_values_before_upload") < task.index(
        "Last, and only after all field_values_before_upload"
    )


def test_build_fill_plan_application_task_omits_unresolved_needs_answer_fields() -> None:
    fill_plan = make_fill_plan()
    fill_plan.needs_answer_fields.append(
        ApplicationFillNeedsAnswerField(
            label="Earliest available start date",
            reason="No safe candidate or reviewed package value is available.",
            required=True,
            input_type="text",
        )
    )

    task = build_fill_plan_application_task(fill_plan)

    assert '"needs_answer_fields"' not in task
    assert "Earliest available start date" not in task


def test_open_apply_url_blocks_unresolved_needs_answer_fields(tmp_path: Path) -> None:
    fill_plan = make_fill_plan()
    fill_plan.needs_answer_fields.append(
        ApplicationFillNeedsAnswerField(
            label="Earliest available start date",
            reason="No safe candidate or reviewed package value is available.",
            required=True,
            input_type="text",
        )
    )

    with pytest.raises(BrowserUseLaunchError, match="Save reviewed values"):
        open_apply_url_with_browser_use_fill_plan(
            "https://example.com/apply/automation-engineer",
            fill_plan=fill_plan,
            log_dir=tmp_path,
        )


def test_build_fill_plan_application_task_includes_promoted_manual_review_values() -> None:
    fill_plan = make_fill_plan()
    fill_plan.field_values.append(
        ApplicationFillFieldValue(
            label="Earliest available start date",
            value="Immediately",
            required=True,
            input_type="text",
            source="manual_review",
            confidence="high",
        )
    )

    task = build_fill_plan_application_task(fill_plan)

    assert '"label": "Earliest available start date"' in task
    assert '"value": "Immediately"' in task
    assert '"source": "manual_review"' in task


def test_open_apply_url_blocks_unreviewed_blocked_fields(tmp_path: Path) -> None:
    fill_plan = make_fill_plan()
    fill_plan.blocked_fields.append(
        ApplicationFillBlockedField(
            label="Unreviewed privacy gate",
            reason="Consent requires user review.",
            required=True,
            input_type="checkbox",
            source="application_requirements",
            confidence="medium",
            evidence_status="interpreted_only",
        )
    )

    with pytest.raises(BrowserUseLaunchError, match="previously blocked"):
        open_apply_url_with_browser_use_fill_plan(
            "https://example.com/apply/automation-engineer",
            fill_plan=fill_plan,
            log_dir=tmp_path,
        )


def test_open_url_with_browser_use_blocks_when_session_exists(
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

    with pytest.raises(BrowserUseLaunchError, match="already running"):
        open_url_with_browser_use(
            "https://example.com/jobs/second-role",
            log_dir=tmp_path,
            startup_wait_seconds=0,
        )

    assert len(launches) == 1


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


def test_browser_use_agent_max_steps_defaults_to_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BROWSER_USE_AGENT_MAX_STEPS", raising=False)

    assert _browser_use_agent_max_steps() == 120


def test_browser_use_agent_max_steps_allows_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_AGENT_MAX_STEPS", "120")

    assert _browser_use_agent_max_steps() == 120


def test_browser_use_agent_max_steps_has_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_AGENT_MAX_STEPS", "5")

    assert _browser_use_agent_max_steps() == 20


def test_browser_use_agent_max_steps_ignores_invalid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_AGENT_MAX_STEPS", "not-a-number")

    assert _browser_use_agent_max_steps() == 120


def test_browser_use_chat_model_wraps_internal_openai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_client = object()
    wrapped_client = object()

    class FakeChatModel:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def get_client(self) -> object:
            return raw_client

    wrapped_inputs: list[object] = []

    def fake_wrap_openai_client(client: object) -> object:
        wrapped_inputs.append(client)
        return wrapped_client

    monkeypatch.setattr(
        "src.browser_use_visible_runner.wrap_openai_client",
        fake_wrap_openai_client,
    )

    llm = _build_traced_browser_use_chat_model(
        FakeChatModel,
        model="gpt-4.1-mini",
        temperature=0.2,
        api_key="test-key",
    )

    assert llm.kwargs == {
        "model": "gpt-4.1-mini",
        "temperature": 0.2,
        "api_key": "test-key",
    }
    assert llm.get_client() is wrapped_client
    assert wrapped_inputs == [raw_client]


def test_browser_use_agent_run_uses_named_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    langsmith_module = type(sys)("langsmith")

    def fake_traceable(*, name: str, run_type: str):
        calls.append((name, run_type))

        def decorator(func):
            async def wrapper(*args: object, **kwargs: object) -> object:
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    class FakeAgent:
        async def run(self, *, max_steps: int) -> str:
            return f"ran:{max_steps}"

    langsmith_module.traceable = fake_traceable
    monkeypatch.setitem(sys.modules, "langsmith", langsmith_module)
    monkeypatch.setattr("src.observability.langsmith_enabled", lambda: True)

    result = asyncio.run(_run_browser_use_apply_agent(FakeAgent(), max_steps=12))

    assert result == "ran:12"
    assert calls == [("browser_use_apply_agent", "chain")]


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


def test_close_other_pages_keeps_active_target_focused() -> None:
    class FakePage:
        def __init__(self, target_id: str) -> None:
            self._target_id = target_id

    class FakeBrowser:
        def __init__(self) -> None:
            self.active_page = FakePage("target-active")
            self.other_page = FakePage("target-other")
            self.closed_pages: list[str] = []
            self.focused_pages: list[str] = []

        async def get_pages(self) -> list[FakePage]:
            return [self.other_page, self.active_page]

        async def close_page(self, page: FakePage) -> None:
            self.closed_pages.append(page._target_id)

        async def get_or_create_cdp_session(self, target_id: str, *, focus: bool) -> None:
            if focus:
                self.focused_pages.append(target_id)

    browser = FakeBrowser()

    closed_count = asyncio.run(_close_other_pages(browser, browser.active_page))

    assert closed_count == 1
    assert browser.closed_pages == ["target-other"]
    assert browser.focused_pages == ["target-active"]


def test_page_has_interactive_content_rejects_blank_page() -> None:
    class FakePage:
        async def evaluate(self, _script: str) -> str:
            return '{"href": "about:blank", "bodyTextLength": 0, "controlCount": 0}'

    assert asyncio.run(_page_has_interactive_content(FakePage())) is False


def test_page_has_interactive_content_accepts_loaded_form() -> None:
    class FakePage:
        async def evaluate(self, _script: str) -> str:
            return (
                '{"href": "https://example.com/apply", '
                '"bodyTextLength": 42, "controlCount": 3}'
            )

    assert asyncio.run(_page_has_interactive_content(FakePage())) is True


def test_open_page_with_retries_retries_navigation_until_controls_load() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.goto_calls: list[str] = []

        async def evaluate(self, _script: str) -> str:
            if self.goto_calls:
                return (
                    '{"href": "https://example.com/apply", '
                    '"bodyTextLength": 42, "controlCount": 3}'
                )
            return '{"href": "about:blank", "bodyTextLength": 0, "controlCount": 0}'

        async def goto(self, url: str) -> None:
            self.goto_calls.append(url)

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def new_page(self, url: str) -> FakePage:
            assert url == "https://example.com/apply"
            return self.page

    browser = FakeBrowser()

    page = asyncio.run(
        _open_page_with_retries(
            browser,
            "https://example.com/apply",
            ready_wait_seconds=0.01,
            poll_interval_seconds=0.001,
        )
    )

    assert page is browser.page
    assert browser.page.goto_calls == ["https://example.com/apply"]


def test_open_page_with_retries_strict_waits_for_loaded_form() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.goto_calls: list[str] = []

        async def evaluate(self, _script: str) -> str:
            if self.goto_calls:
                return (
                    '{"href": "https://example.com/apply", '
                    '"bodyTextLength": 42, "controlCount": 3, "readyState": "complete"}'
                )
            return (
                '{"href": "about:blank", "bodyTextLength": 0, '
                '"controlCount": 0, "readyState": "complete"}'
            )

        async def goto(self, url: str) -> None:
            self.goto_calls.append(url)

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def new_page(self, url: str) -> FakePage:
            assert url == "https://example.com/apply"
            return self.page

    browser = FakeBrowser()

    page = asyncio.run(
        _open_page_with_retries(
            browser,
            "https://example.com/apply",
            require_interactive_page=True,
            page_ready_timeout_seconds=0.1,
            ready_wait_seconds=0.001,
            poll_interval_seconds=0.001,
        )
    )

    assert page is browser.page
    assert browser.page.goto_calls == ["https://example.com/apply"]


def test_open_page_with_retries_strict_fails_when_page_stays_blank() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.goto_calls: list[str] = []

        async def evaluate(self, _script: str) -> str:
            return (
                '{"href": "about:blank", "bodyTextLength": 0, '
                '"controlCount": 0, "readyState": "complete"}'
            )

        async def goto(self, url: str) -> None:
            self.goto_calls.append(url)

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def new_page(self, url: str) -> FakePage:
            assert url == "https://example.com/apply"
            return self.page

    browser = FakeBrowser()

    with pytest.raises(RuntimeError, match="could not load an interactive apply page"):
        asyncio.run(
            _open_page_with_retries(
                browser,
                "https://example.com/apply",
                require_interactive_page=True,
                page_ready_timeout_seconds=0.01,
                ready_wait_seconds=0.001,
                poll_interval_seconds=0.001,
            )
        )

    assert browser.page.goto_calls


def test_open_page_with_retries_non_strict_allows_blank_page_for_manual_use() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.goto_calls: list[str] = []

        async def evaluate(self, _script: str) -> str:
            return (
                '{"href": "about:blank", "bodyTextLength": 0, '
                '"controlCount": 0, "readyState": "complete"}'
            )

        async def goto(self, url: str) -> None:
            self.goto_calls.append(url)

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def new_page(self, url: str) -> FakePage:
            assert url == "https://example.com/apply"
            return self.page

    browser = FakeBrowser()

    page = asyncio.run(
        _open_page_with_retries(
            browser,
            "https://example.com/apply",
            max_attempts=1,
            ready_wait_seconds=0.001,
            poll_interval_seconds=0.001,
        )
    )

    assert page is browser.page
    assert browser.page.goto_calls == []


def make_fill_plan(upload_path: str = "/tmp/candidate/cv.pdf") -> ApplicationFillPlan:
    return ApplicationFillPlan(
        job_id="job-123",
        apply_url="https://example.com/apply/automation-engineer",
        review_status="reviewed",
        source_metadata={
            "candidate_documents": {
                "cv": {"file_path": upload_path},
                "optional_documents": [],
            },
            "package_upload_artifacts": [],
        },
        field_values=[
            ApplicationFillFieldValue(
                label="Vorname",
                value="Taylor",
                required=True,
                input_type="text",
                source="manual_review",
                confidence="high",
                literal_evidence=["Vorname"],
                evidence_source="control_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="Privacy acknowledgement",
                value="true",
                required=True,
                input_type="checkbox",
                options=["true", "false"],
                source="manual_review",
                confidence="high",
                literal_evidence=["Privacy acknowledgement"],
                evidence_source="form_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="Internal application",
                value="false",
                required=False,
                input_type="checkbox",
                source="manual_review",
                confidence="high",
                literal_evidence=["Internal application"],
                evidence_source="control_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="Employee referral",
                value="",
                required=False,
                input_type="text",
                source="manual_review",
                confidence="high",
                literal_evidence=["Employee referral"],
                evidence_source="control_label",
                evidence_status="literal_verified",
            ),
            ApplicationFillFieldValue(
                label="ATS gate: external application system",
                value="true",
                required=True,
                input_type="checkbox",
                options=["true", "false"],
                source="manual_review",
                confidence="high",
                literal_evidence=["Application system gate text"],
                evidence_source="visible_text_excerpt",
                evidence_status="partial_match",
            ),
        ],
        upload_files=[
            ApplicationFillUploadFile(
                label="Lebenslauf",
                file_path=upload_path,
                document_type="cv",
                required=True,
                source="manual_review",
                confidence="high",
                literal_evidence=["Lebenslauf"],
                evidence_source="evidence_match",
                evidence_status="literal_verified",
            )
        ],
        blocked_fields=[],
        submit_guard_labels=["Weiter & Prüfen", "Submit"],
    )
