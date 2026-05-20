from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application_requirements import (
    APPLICATION_PAGE_SNAPSHOT_FILENAME,
    BrowserInspectionFailure,
    LLMApplicationRequirementsResponse,
    build_application_page_snapshot,
    discover_application_requirements,
    extract_application_requirements_with_llm,
    inspect_application_page_agent,
    run_requirements_discovery_graph,
    save_application_page_snapshot,
    save_application_requirements,
)
from src.job_intake import create_job_listing
from src.schemas import (
    ApplicationFormField,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
)
from src.storage import load_model

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_job(apply_url: str = "https://example.com/apply/automation-engineer"):
    return create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url=apply_url,
    )


def discovered_requirements(job, *, confidence: str = "high") -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=job.apply_url,
        source_url=job.source_url,
        status="discovered",
        job_preserving=True,
        required_documents=[
            ApplicationRequirementFinding(
                label="CV or resume",
                required=True,
                evidence="Upload CV",
                confidence="high",
                constraints=[".pdf,.docx"],
            )
        ],
        upload_expectations=[
            ApplicationRequirementFinding(
                label="Upload CV",
                required=True,
                evidence="Upload CV",
                confidence="high",
                constraints=[".pdf,.docx"],
            )
        ],
        screening_questions=[
            ApplicationScreeningQuestion(
                question="Are you authorized to work in Germany?",
                required=True,
                input_type="select",
                evidence="Are you authorized to work in Germany?",
                confidence="high",
            )
        ],
        profile_fields=[
            ApplicationFormField(
                name="email",
                label="Email",
                required=True,
                input_type="email",
                evidence="Email",
                confidence="high",
            )
        ],
        consent_requirements=[
            ApplicationRequirementFinding(
                label="Privacy consent",
                required=True,
                evidence="I consent to privacy and data processing terms.",
                confidence="high",
            )
        ],
        motivation_letter=ApplicationRequirementFinding(
            label="Motivation or cover letter",
            required=True,
            evidence="Please upload a cover letter.",
            confidence="medium",
        ),
        deadlines=[
            ApplicationRequirementFinding(
                label="Apply by 2026-06-30",
                evidence="Apply by 2026-06-30.",
                confidence="medium",
            )
        ],
        contact_or_fallback=[
            ApplicationRequirementFinding(
                label="recruiting@example.com",
                evidence="Contact recruiting@example.com.",
                confidence="medium",
            )
        ],
        source_evidence=["Upload CV", "Please upload a cover letter."],
        confidence=confidence,
    )


def blocked_requirements(job) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=job.apply_url,
        source_url=job.source_url,
        status="blocked",
        blocked_reason="Apply page does not preserve the selected job identity.",
        job_preserving=False,
        missing_or_uncertain=[
            "Verify the apply URL manually or resolve a job-specific application URL."
        ],
        source_evidence=["Search jobs, join our talent community, browse openings."],
        confidence="low",
    )


def find_property_schema(schema: dict, property_name: str) -> dict | None:
    properties = schema.get("properties", {})
    if property_name in properties:
        return properties[property_name]
    for definition in schema.get("$defs", {}).values():
        found = find_property_schema(definition, property_name)
        if found is not None:
            return found
    return None


def test_llm_application_requirements_schema_does_not_emit_uri_formats() -> None:
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(LLMApplicationRequirementsResponse)

    for field_name in ("apply_url", "source_url"):
        field_schema = find_property_schema(schema, field_name)
        assert field_schema is not None
        assert field_schema["type"] == "string"
        assert field_schema.get("format") != "uri"


def test_llm_extractor_uses_llm_safe_response_model(monkeypatch: pytest.MonkeyPatch) -> None:
    job = make_job()
    parse_calls = []
    parsed_payload = LLMApplicationRequirementsResponse(
        job_id="llm-job",
        apply_url="https://llm.example/apply",
        source_url="https://llm.example/source",
        status="discovered",
        job_preserving=True,
        required_documents=[
            ApplicationRequirementFinding(
                label="CV",
                required=True,
                evidence="Upload CV",
                confidence="high",
            )
        ],
        confidence="high",
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    requirements = extract_application_requirements_with_llm(
        job,
        build_application_page_snapshot(
            job,
            requested_url=str(job.apply_url),
            final_url="https://example.com/apply/automation-engineer",
            html="Upload CV",
            fetch_status=200,
            content_type="text/html",
        ),
    )

    assert parse_calls[0]["text_format"] is LLMApplicationRequirementsResponse
    assert parse_calls[0]["text_format"] is not ApplicationRequirements
    assert parse_calls[0]["temperature"] == 0.0
    assert parse_calls[0]["max_output_tokens"] == 6000
    assert parse_calls[0]["timeout"] == 60
    assert parse_calls[0]["truncation"] == "disabled"
    assert isinstance(requirements, ApplicationRequirements)
    assert requirements.required_documents[0].label == "CV"
    assert requirements.workflow_trace is not None
    assert requirements.workflow_trace.workflow_name == "application_requirements"


def test_llm_extractor_converts_output_to_persisted_requirements_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job()
    parsed_payload = LLMApplicationRequirementsResponse(
        job_id="wrong-job",
        apply_url="https://example.com/wrong-apply",
        source_url="https://example.com/wrong-source",
        status="discovered",
        job_preserving=True,
        source_evidence=["Upload CV"],
        confidence="high",
    )

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=parsed_payload)

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    requirements = extract_application_requirements_with_llm(
        job,
        build_application_page_snapshot(
            job,
            requested_url=str(job.apply_url),
            final_url="https://example.com/apply/automation-engineer",
            html="Upload CV",
            fetch_status=200,
            content_type="text/html",
        ),
    )

    assert isinstance(requirements, ApplicationRequirements)
    assert requirements.job_id == job.id
    assert str(requirements.apply_url) == str(job.apply_url)
    assert str(requirements.source_url) == str(job.source_url)
    assert requirements.source_evidence == ["Upload CV"]
    assert requirements.workflow_trace is not None


def test_llm_extractor_wraps_openai_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponses:
        def parse(self, **_kwargs):
            raise Exception("Invalid schema for response_format")

    monkeypatch.setattr(
        "src.llm_client.get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )

    with pytest.raises(RuntimeError, match="AI application requirements extraction failed"):
        extract_application_requirements_with_llm(
            make_job(),
            ApplicationPageSnapshot(
                requested_url="https://example.com/apply/automation-engineer",
                final_url="https://example.com/apply/automation-engineer",
                errors=["No content"],
            ),
        )


def test_discovery_delegates_application_contract_to_llm_extractor() -> None:
    job = make_job()
    calls = []

    def fake_extractor(received_job, snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        calls.append((received_job, snapshot))
        return discovered_requirements(received_job)

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("uploads_and_consent_form.html"),
        final_url="https://ats.example.com/jobs/automation-engineer/apply",
        extractor=fake_extractor,
    )

    assert calls[0][0] == job
    assert "Cover letter" in calls[0][1].visible_text_excerpt
    assert calls[0][1].final_url == "https://ats.example.com/jobs/automation-engineer/apply"
    assert requirements.status == "discovered"
    assert requirements.job_preserving is True
    assert requirements.required_documents[0].label == "CV or resume"
    assert requirements.screening_questions[0].question == "Are you authorized to work in Germany?"
    assert requirements.consent_requirements[0].label == "Privacy consent"
    assert requirements.motivation_letter is not None


def test_generic_career_page_blocks_before_llm_extraction() -> None:
    job = make_job(apply_url="https://example.com/careers")

    def fail_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        raise AssertionError("The LLM extractor should not run for generic career pages.")

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("generic_career_page.html"),
        extractor=fail_extractor,
    )

    assert requirements.status == "blocked"
    assert requirements.job_preserving is False
    assert requirements.blocked_reason == (
        "Apply page is a generic careers page and does not preserve the selected job."
    )


def test_discovery_normalizes_identity_fields_from_llm_output() -> None:
    job = make_job()

    def fake_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        requirements = discovered_requirements(job)
        requirements.job_id = "wrong-job"
        requirements.apply_url = "https://example.com/wrong"
        requirements.source_url = "https://example.com/wrong-source"
        return requirements

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("simple_ats_form.html"),
        extractor=fake_extractor,
    )

    assert requirements.job_id == job.id
    assert str(requirements.apply_url) == str(job.apply_url)
    assert str(requirements.source_url) == str(job.source_url)


def test_non_preserving_discovered_output_is_converted_to_blocked() -> None:
    job = make_job()

    def fake_extractor(received_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        requirements = discovered_requirements(received_job)
        requirements.job_preserving = False
        return requirements

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("simple_ats_form.html"),
        extractor=fake_extractor,
    )

    assert requirements.status == "blocked"
    assert requirements.blocked_reason == (
        "Apply page does not preserve the selected job identity."
    )


@pytest.mark.parametrize(
    ("apply_url", "message"),
    [
        ("", "Apply URL is required before discovering application requirements."),
        ("mailto:jobs@example.com", "Apply URL must be a working http or https URL"),
        (
            "https://example.com/jobs/automation-engineer",
            "Apply URL must point to the application destination",
        ),
    ],
)
def test_invalid_apply_url_values_stop_before_llm_extraction(
    apply_url: str,
    message: str,
) -> None:
    job = make_job()
    if apply_url:
        job.apply_url = apply_url
    else:
        job.apply_url = None

    def fail_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        raise AssertionError("The LLM extractor should not run for invalid apply URLs.")

    with pytest.raises(ValueError, match=message):
        discover_application_requirements(
            job,
            page_content=fixture_html("simple_ats_form.html"),
            extractor=fail_extractor,
        )


def test_missing_local_page_content_blocks_before_llm_extraction() -> None:
    job = make_job()

    def fail_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        raise AssertionError("The LLM extractor should not run without inspectable content.")

    requirements = discover_application_requirements(
        job,
        page_content="",
        extractor=fail_extractor,
    )

    assert requirements.status == "blocked"
    assert requirements.job_preserving is False
    assert "No local page content supplied." in requirements.blocked_reason
    assert "No static HTML content was available" in requirements.blocked_reason
    assert requirements.confidence == "low"


def test_redirected_apply_page_without_job_identity_blocks_before_llm_extraction() -> None:
    job = make_job()

    def fail_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        raise AssertionError("The LLM extractor should not run for non-preserving redirects.")

    requirements = discover_application_requirements(
        job,
        page_content=(
            "<html><body><h1>Product Manager</h1>"
            "<form><input name='cv'></form></body></html>"
        ),
        final_url="https://ats.example.com/jobs/product-manager/apply",
        extractor=fail_extractor,
    )

    assert requirements.status == "blocked"
    assert requirements.job_preserving is False
    assert requirements.blocked_reason == (
        "Apply page redirected without preserving the selected job identity."
    )
    assert requirements.confidence == "low"


def test_js_shell_snapshot_blocks_before_llm_extraction() -> None:
    job = make_job()

    def fake_inspector(received_job) -> ApplicationPageSnapshot:
        return ApplicationPageSnapshot(
            requested_url=str(received_job.apply_url),
            final_url=str(received_job.apply_url),
            fetch_status=200,
            visible_text_excerpt="Loading app",
            errors=["Playwright browser fallback is unavailable or failed."],
        )

    def fail_extractor(_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        raise AssertionError("The LLM extractor should not run for a JS shell snapshot.")

    state = run_requirements_discovery_graph(
        job,
        inspector=fake_inspector,
        extractor=fail_extractor,
    )

    assert state["requirements"].status == "blocked"
    assert state["requirements"].blocked_reason == (
        "Apply page could not be inspected: "
        "Playwright browser fallback is unavailable or failed."
    )


def test_application_requirements_are_saved_separately_from_normalized_job(
    tmp_path: Path,
) -> None:
    job = make_job()
    requirements = discovered_requirements(job)

    saved_path = save_application_requirements(tmp_path, requirements)
    reloaded = load_model(saved_path, ApplicationRequirements)

    assert saved_path.name == "application_requirements.json"
    assert saved_path.parent.name == requirements.job_id
    assert not (saved_path.parent / "normalized_job.json").exists()
    assert reloaded == requirements


def test_inspection_snapshot_extracts_controls_and_multilingual_evidence() -> None:
    job = make_job()

    snapshot = inspect_application_page_agent(
        job,
        page_content=fixture_html("uploads_and_consent_form.html"),
        final_url="https://ats.example.com/jobs/automation-engineer/apply",
    )

    assert any("Cover letter" in match for match in snapshot.evidence_matches)
    assert any("privacy" in match.lower() for match in snapshot.evidence_matches)
    assert any(control.input_type == "file" for control in snapshot.controls)
    assert any(form.controls for form in snapshot.forms)


def test_embedded_upload_component_json_is_summarized() -> None:
    job = make_job()
    html = """
    <html><head><title>Apply</title></head><body>
      <h1>Automation Engineer</h1>
      <script type="application/json" id="seed">
        {"components":[{"type":"upload","required":true,"label":"CV","maxSizeMb":10}]}
      </script>
    </body></html>
    """

    snapshot = inspect_application_page_agent(job, page_content=html)

    assert snapshot.embedded_json_summaries
    assert "maxSizeMb" in snapshot.embedded_json_summaries[0]["summary"]
    assert snapshot.job_preserving_signals == ["title: Automation Engineer"]


def test_generic_career_page_snapshot_has_no_job_preserving_signal() -> None:
    job = make_job(apply_url="https://example.com/careers")

    snapshot = inspect_application_page_agent(
        job,
        page_content=fixture_html("generic_career_page.html"),
    )

    assert snapshot.job_preserving_signals == []
    assert any("Search" in match or "jobs" in match.lower() for match in snapshot.evidence_matches)


def test_snapshot_persistence_clips_and_redacts_sensitive_values(tmp_path: Path) -> None:
    job = make_job()
    html = (
        "<html><head><title>Apply</title></head><body>"
        "<input type='hidden' name='csrf_token' value='supersecretvalue123'>"
        + ("Upload CV. " * 10000)
        + "</body></html>"
    )
    snapshot = inspect_application_page_agent(job, page_content=html)

    saved_path = save_application_page_snapshot(tmp_path, job.id, snapshot)
    reloaded = load_model(saved_path, ApplicationPageSnapshot)

    assert saved_path.name == APPLICATION_PAGE_SNAPSHOT_FILENAME
    assert "supersecretvalue123" not in reloaded.raw_html_excerpt
    assert "[REDACTED]" in reloaded.raw_html_excerpt
    assert "[TRUNCATED]" in reloaded.raw_html_excerpt


def test_requirements_graph_invokes_inspection_before_llm_extraction() -> None:
    job = make_job()
    calls = []

    def fake_inspector(received_job) -> ApplicationPageSnapshot:
        calls.append("inspect_application_page_agent")
        return ApplicationPageSnapshot(
            requested_url=str(received_job.apply_url),
            final_url="https://ats.example.com/jobs/automation-engineer/apply",
            evidence_matches=["Upload CV"],
            job_preserving_signals=["title: Automation Engineer"],
        )

    def fake_extractor(received_job, snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        calls.append("extract_application_requirements")
        assert received_job == job
        assert snapshot.evidence_matches == ["Upload CV"]
        return discovered_requirements(received_job)

    state = run_requirements_discovery_graph(
        job,
        inspector=fake_inspector,
        extractor=fake_extractor,
    )

    assert calls == ["inspect_application_page_agent", "extract_application_requirements"]
    assert state["requirements"].job_id == job.id


def test_selected_job_identity_overrides_llm_output_in_graph() -> None:
    job = make_job()

    def fake_extractor(received_job, _snapshot: ApplicationPageSnapshot) -> ApplicationRequirements:
        requirements = discovered_requirements(received_job)
        requirements.job_id = "wrong-job"
        requirements.apply_url = "https://example.com/wrong"
        requirements.source_url = "https://example.com/wrong-source"
        return requirements

    state = run_requirements_discovery_graph(
        job,
        page_content="Upload CV",
        extractor=fake_extractor,
    )

    assert state["requirements"].job_id == job.id
    assert str(state["requirements"].apply_url) == str(job.apply_url)
    assert str(state["requirements"].source_url) == str(job.source_url)


def test_js_shell_static_html_records_playwright_absence_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job()

    monkeypatch.setattr(
        "src.application_requirements.fetch_application_page",
        lambda _url: {
            "requested_url": str(job.apply_url),
            "final_url": str(job.apply_url),
            "html": "<html><body><div id='root'>Loading app</div></body></html>",
            "fetch_status": 200,
            "content_type": "text/html",
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "src.application_requirements.inspect_application_page_with_browser",
        lambda _job, _url: BrowserInspectionFailure(
            "Playwright browser fallback failed: Error: browser crashed."
        ),
    )

    snapshot = inspect_application_page_agent(
        job,
    )

    assert snapshot.visible_text_excerpt == "Loading app"
    assert "Playwright browser fallback failed: Error: browser crashed." in snapshot.errors
