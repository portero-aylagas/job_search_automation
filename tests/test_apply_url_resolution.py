from __future__ import annotations

import pytest

from src.apply_url_resolution import (
    choose_apply_url_deterministically,
    extract_apply_url_candidates,
    normalize_candidate_url,
    resolve_apply_url_agentically,
    run_apply_url_resolution_graph,
    verify_apply_url_candidates,
)
from src.llm_job_extraction import ApplyUrlResolution

SOURCE_URL = "https://example.com/jobs/automation-engineer-12345"


def test_extracts_normal_apply_link_from_html() -> None:
    html = """
    <html><body>
      <a href="https://ats.example.com/jobs/12345/apply">Apply now</a>
    </body></html>
    """

    result = extract_apply_url_candidates(html, SOURCE_URL)

    assert len(result["candidates"]) == 1
    assert result["candidates"][0].url == "https://ats.example.com/jobs/12345/apply"
    assert result["candidates"][0].source == "href"
    assert result["candidates"][0].confidence == "high"


def test_extracts_german_jetzt_bewerben_link() -> None:
    html = """
    <html><body>
      <a href="/karriere/bewerbung?job_id=12345">Jetzt bewerben</a>
    </body></html>
    """

    result = extract_apply_url_candidates(html, SOURCE_URL)

    assert len(result["candidates"]) == 1
    assert result["candidates"][0].url == "https://example.com/karriere/bewerbung?job_id=12345"
    assert result["candidates"][0].label == "Jetzt bewerben"


def test_relative_apply_url_normalization() -> None:
    assert (
        normalize_candidate_url("../apply/automation-engineer?job_id=12345", SOURCE_URL)
        == "https://example.com/apply/automation-engineer?job_id=12345"
    )


def test_rejects_mailto_tel_newsletter_and_talent_community_links() -> None:
    html = """
    <html><body>
      <a href="mailto:jobs@example.com">Apply by email</a>
      <a href="tel:+49123456789">Apply by phone</a>
      <a href="/newsletter">Application newsletter</a>
      <a href="/talent-community">Apply through our talent community</a>
    </body></html>
    """

    result = extract_apply_url_candidates(html, SOURCE_URL)

    assert result["candidates"] == []
    reasons = [rejection.reason for rejection in result["rejected_candidates"]]
    assert "Candidate is an email or phone link, not an application URL." in reasons
    assert "Candidate points to a non-application destination." in reasons
    assert "Candidate points to a talent-community signup." in reasons


def test_rejects_same_page_apply_link() -> None:
    html = f"""
    <html><body>
      <a href="{SOURCE_URL}">Apply now</a>
    </body></html>
    """

    result = extract_apply_url_candidates(html, SOURCE_URL)

    assert result["candidates"] == []
    assert result["rejected_candidates"][0].reason == (
        "Candidate matches the source job-description URL."
    )


def test_verifies_candidate_when_destination_preserves_title_and_company() -> None:
    html = """
    <html><body>
      <a href="/apply/automation-engineer?job_id=12345">Apply now</a>
    </body></html>
    """
    result = extract_apply_url_candidates(html, SOURCE_URL)

    def fake_fetcher(url: str):
        return {
            "requested_url": url,
            "final_url": "https://ats.example.com/apply/automation-engineer?job_id=12345",
            "html": "<h1>Automation Engineer</h1><p>Example Co application form</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    verified, rejected = verify_apply_url_candidates(
        result["candidates"],
        source_url=SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="12345",
        fetcher=fake_fetcher,
    )

    assert rejected == []
    assert verified[0].status == "verified"
    assert verified[0].final_url == "https://ats.example.com/apply/automation-engineer?job_id=12345"
    assert "title: Automation Engineer" in verified[0].job_preserving_signals
    assert "company: Example Co" in verified[0].job_preserving_signals
    assert "source_job_id: 12345" in verified[0].job_preserving_signals


def test_workflow_resolves_verified_candidate_without_live_network_or_openai() -> None:
    html = """
    <html><body>
      <a href="/apply/automation-engineer?job_id=12345">Apply now</a>
    </body></html>
    """

    def fake_fetcher(url: str):
        return {
            "requested_url": url,
            "final_url": "https://ats.example.com/apply/automation-engineer?job_id=12345",
            "html": "<h1>Automation Engineer</h1><p>Example Co application form</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    state = run_apply_url_resolution_graph(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="12345",
        page_content=html,
        fetcher=fake_fetcher,
        ranker=choose_apply_url_deterministically,
    )

    assert state["resolution"].status == "resolved"
    assert (
        state["resolution"].apply_url
        == "https://ats.example.com/apply/automation-engineer?job_id=12345"
    )
    assert state["resolution"].confidence == "high"


def test_resolution_is_not_found_when_no_candidate_exists() -> None:
    resolution = resolve_apply_url_agentically(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        page_content="<html><body><h1>Automation Engineer</h1></body></html>",
    )

    assert resolution.status == "not_found"
    assert resolution.apply_url == ""
    assert resolution.rejected_candidates == []


def test_workflow_marks_static_candidate_branch() -> None:
    html = """
    <html><body>
      <a href="/apply/automation-engineer?job_id=12345">Apply now</a>
    </body></html>
    """

    def fake_fetcher(url: str):
        return {
            "requested_url": url,
            "final_url": "https://ats.example.com/apply/automation-engineer?job_id=12345",
            "html": "<h1>Automation Engineer</h1><p>Example Co application form</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    state = run_apply_url_resolution_graph(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="12345",
        page_content=html,
        fetcher=fake_fetcher,
        ranker=choose_apply_url_deterministically,
    )

    assert state["candidate_discovery_mode"] == "static_candidates_found"


def test_llm_suggested_candidate_is_rejected_when_job_identity_is_not_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.apply_url_resolution.resolve_apply_url_from_url",
        lambda source_url, *, title="", company="": ApplyUrlResolution(
            status="resolved",
            apply_url="https://ats.example.com/apply/other-role",
            notes="Fallback found an apply page.",
            evidence=["candidate from external inspection"],
            rejected_candidates=[],
            confidence="medium",
        ),
    )

    def fake_fetcher(url: str):
        return {
            "requested_url": url,
            "final_url": url,
            "html": "<h1>Join our talent community</h1><p>General careers portal</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    state = run_apply_url_resolution_graph(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="12345",
        page_content="<html><body><h1>Automation Engineer</h1></body></html>",
        fetcher=fake_fetcher,
        ranker=choose_apply_url_deterministically,
    )

    assert state["candidate_discovery_mode"] == "llm_fallback_candidate_found"
    assert state["candidates"][0].source == "llm_suggested"
    assert state["candidates"][0].status == "rejected"
    assert state["resolution"].status == "needs_review"
    assert state["resolution"].apply_url == ""
    assert any(
        rejection.reason == "Destination appears generic or non-application related."
        for rejection in state["rejected_candidates"]
    )


def test_llm_suggested_candidate_is_resolved_only_after_deterministic_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.apply_url_resolution.resolve_apply_url_from_url",
        lambda source_url, *, title="", company="": ApplyUrlResolution(
            status="resolved",
            apply_url="https://ats.example.com/apply/automation-engineer?job_id=12345",
            notes="Fallback found an apply page.",
            evidence=["candidate from external inspection"],
            rejected_candidates=[],
            confidence="medium",
        ),
    )

    def fake_fetcher(url: str):
        return {
            "requested_url": url,
            "final_url": "https://ats.example.com/apply/automation-engineer?job_id=12345",
            "html": "<h1>Automation Engineer</h1><p>Example Co application form</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    state = run_apply_url_resolution_graph(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="12345",
        page_content="<html><body><h1>Automation Engineer</h1></body></html>",
        fetcher=fake_fetcher,
        ranker=choose_apply_url_deterministically,
    )

    assert state["candidate_discovery_mode"] == "llm_fallback_candidate_found"
    assert state["candidates"][0].source == "llm_suggested"
    assert state["candidates"][0].status == "verified"
    assert state["resolution"].status == "resolved"
    assert (
        state["resolution"].apply_url
        == "https://ats.example.com/apply/automation-engineer?job_id=12345"
    )


def test_workflow_marks_no_candidates_branch_when_static_and_fallback_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.apply_url_resolution.resolve_apply_url_from_url",
        lambda source_url, *, title="", company="": ApplyUrlResolution(
            status="not_found",
            apply_url="",
            notes="No apply URL found.",
            evidence=[],
            rejected_candidates=[],
            confidence="low",
        ),
    )

    state = run_apply_url_resolution_graph(
        SOURCE_URL,
        title="Automation Engineer",
        company="Example Co",
        page_content="<html><body><h1>Automation Engineer</h1></body></html>",
        ranker=choose_apply_url_deterministically,
    )

    assert state["candidate_discovery_mode"] == "no_candidates_at_all"
    assert state["resolution"].status == "not_found"
