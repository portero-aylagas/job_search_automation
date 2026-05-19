from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from src.job_intake import choose_valid_apply_url, validate_apply_url
from src.page_inspection import (
    fetch_page,
    page_needs_browser_fallback,
    parse_page_document,
)
from src.schemas import JobPageLink, JobPageSnapshot
from src.storage import save_model

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
JOB_PAGE_SNAPSHOT_FILENAME = "job_page_snapshot.json"
RUNTIME_DATA_DIR = Path("data/runtime")


class DynamicJobDetail(BaseModel):
    name: str
    value: str
    category: str = ""
    source_text: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class ExtractedJobData(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    remote_policy: str = ""
    apply_url: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    salary: str = ""
    posted_date: str = ""
    source_job_id: str = ""
    confidence: str = ""
    dynamic_fields: list[DynamicJobDetail] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)


class RejectedApplyCandidate(BaseModel):
    url: str = ""
    reason: str = ""
    evidence: str = ""


class ApplyUrlResolution(BaseModel):
    status: Literal["resolved", "needs_review", "not_found"] = "not_found"
    apply_url: str = ""
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)
    rejected_candidates: list[RejectedApplyCandidate] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


JobDataExtractor = Callable[[str, JobPageSnapshot], ExtractedJobData]
ApplyResolver = Callable[[str, JobPageSnapshot, ExtractedJobData], ApplyUrlResolution]
JobPageInspector = Callable[[str], JobPageSnapshot]


class JobIntakeState(TypedDict, total=False):
    source_url: str
    inspector: JobPageInspector | None
    extractor: JobDataExtractor | None
    apply_resolver: ApplyResolver | None
    snapshot: JobPageSnapshot
    extracted_job_data: ExtractedJobData
    apply_url_resolution: ApplyUrlResolution
    extraction_mode: str


def _validate_source_url(source_url: str) -> str:
    normalized_url = source_url.strip()

    if not normalized_url:
        raise ValueError("Enter a job URL.")

    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Enter a full job URL, including https://.")

    return normalized_url


def _get_openai_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before extracting job data with AI.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Python package before using AI extraction.") from exc

    return OpenAI()


def _web_search_tool() -> dict:
    return {
        "type": "web_search",
        "search_context_size": "high",
    }


def extract_job_data_from_url(source_url: str) -> ExtractedJobData:
    state = run_job_intake_graph(source_url)
    return state["extracted_job_data"]


def run_job_intake_graph(
    source_url: str,
    *,
    inspector: JobPageInspector | None = None,
    extractor: JobDataExtractor | None = None,
    apply_resolver: ApplyResolver | None = None,
) -> JobIntakeState:
    normalized_url = _validate_source_url(source_url)
    state: JobIntakeState = {
        "source_url": normalized_url,
        "inspector": inspector,
        "extractor": extractor,
        "apply_resolver": apply_resolver,
    }
    graph = build_job_intake_graph()
    return graph.invoke(state)


def build_job_intake_graph():
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialJobIntakeGraph()

    graph = StateGraph(JobIntakeState)
    graph.add_node("inspect_job_page_agent", _inspect_job_page_node)
    graph.add_node("extract_job_data", _extract_job_data_node)
    graph.add_node("extract_job_data_with_web_search_fallback", _fallback_extract_job_data_node)
    graph.add_node("resolve_apply_url", _resolve_apply_url_node)
    graph.set_entry_point("inspect_job_page_agent")
    graph.add_conditional_edges(
        "inspect_job_page_agent",
        _snapshot_route,
        {
            "snapshot": "extract_job_data",
            "fallback": "extract_job_data_with_web_search_fallback",
        },
    )
    graph.add_edge("extract_job_data", "resolve_apply_url")
    graph.add_edge("extract_job_data_with_web_search_fallback", "resolve_apply_url")
    graph.add_edge("resolve_apply_url", END)
    return graph.compile()


class _SequentialJobIntakeGraph:
    def invoke(self, state: JobIntakeState) -> JobIntakeState:
        next_state = dict(state)
        next_state.update(_inspect_job_page_node(next_state))
        if _snapshot_route(next_state) == "fallback":
            next_state.update(_fallback_extract_job_data_node(next_state))
        else:
            next_state.update(_extract_job_data_node(next_state))
        next_state.update(_resolve_apply_url_node(next_state))
        return next_state


def _inspect_job_page_node(state: JobIntakeState) -> dict[str, JobPageSnapshot]:
    source_url = state["source_url"]
    inspector = state.get("inspector")
    snapshot = (
        inspector(source_url)
        if inspector is not None
        else inspect_job_page_agent(source_url)
    )
    return {"snapshot": snapshot}


def _snapshot_route(state: JobIntakeState) -> Literal["snapshot", "fallback"]:
    return "fallback" if _snapshot_is_insufficient(state["snapshot"]) else "snapshot"


def _extract_job_data_node(state: JobIntakeState) -> dict[str, object]:
    extractor = state.get("extractor") or extract_job_data_with_llm
    extracted = extractor(state["source_url"], state["snapshot"])
    extracted.apply_url = ""
    return {"extracted_job_data": extracted, "extraction_mode": "snapshot"}


def _fallback_extract_job_data_node(state: JobIntakeState) -> dict[str, object]:
    extracted = extract_job_data_with_web_search_fallback(state["source_url"], state["snapshot"])
    extracted.apply_url = ""
    return {"extracted_job_data": extracted, "extraction_mode": "web_search_fallback"}


def _resolve_apply_url_node(state: JobIntakeState) -> dict[str, ApplyUrlResolution]:
    resolver = state.get("apply_resolver") or resolve_apply_url_from_snapshot
    resolution = resolver(
        state["source_url"],
        state["snapshot"],
        state["extracted_job_data"],
    )
    if resolution.status != "resolved" or not resolution.apply_url:
        resolution = resolve_apply_url_with_web_search_fallback(
            state["source_url"],
            title=state["extracted_job_data"].title,
            company=state["extracted_job_data"].company,
            prior_resolution=resolution,
        )
    if resolution.status == "resolved":
        chosen = choose_valid_apply_url(state["source_url"], resolution.apply_url)
        if chosen:
            state["extracted_job_data"].apply_url = chosen
    return {"apply_url_resolution": resolution}


def _snapshot_is_insufficient(snapshot: JobPageSnapshot) -> bool:
    if not snapshot.raw_html_excerpt.strip():
        return True
    if snapshot.fetch_status in {401, 403, 429, 500, 502, 503}:
        return True
    if snapshot.errors and len(snapshot.visible_text_excerpt.strip()) < 200:
        return True
    return page_needs_browser_fallback(
        raw_html_excerpt=snapshot.raw_html_excerpt,
        visible_text_excerpt=snapshot.visible_text_excerpt,
        fetch_status=snapshot.fetch_status,
        has_interactive_elements=bool(snapshot.links or snapshot.buttons or snapshot.forms),
    )


def inspect_job_page_agent(
    source_url: str,
    *,
    page_content: str | None = None,
    final_url: str | None = None,
) -> JobPageSnapshot:
    normalized_url = _validate_source_url(source_url)
    if page_content is not None:
        return build_job_page_snapshot(
            requested_url=normalized_url,
            final_url=final_url or normalized_url,
            html=page_content,
            fetch_status=200 if page_content else None,
            content_type="text/html",
            errors=[] if page_content else ["No local page content supplied."],
        )

    fetch_result = fetch_page(normalized_url)
    snapshot = build_job_page_snapshot(**fetch_result)
    if _snapshot_is_insufficient(snapshot):
        browser_snapshot = inspect_job_page_with_browser(normalized_url)
        if browser_snapshot is not None:
            return browser_snapshot
        snapshot.errors.append("Playwright browser fallback is unavailable or failed.")
    return snapshot


def inspect_job_page_with_browser(url: str) -> JobPageSnapshot | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="networkidle", timeout=15_000)
            html = page.content()
            final_url = page.url
            status = response.status if response is not None else None
            content_type = response.headers.get("content-type", "") if response is not None else ""
            browser.close()
    except Exception:
        return None

    return build_job_page_snapshot(
        requested_url=url,
        final_url=final_url,
        html=html,
        fetch_status=status,
        content_type=content_type,
        errors=[],
        browser_fallback_used=True,
    )


def build_job_page_snapshot(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    fetch_status: int | None,
    content_type: str,
    errors: list[str] | None = None,
    browser_fallback_used: bool = False,
) -> JobPageSnapshot:
    parsed = parse_page_document(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        fetch_status=fetch_status,
        content_type=content_type,
        errors=errors,
        browser_fallback_used=browser_fallback_used,
    )
    candidates = _find_apply_link_candidates(parsed["links"], parsed["buttons"], requested_url)
    return JobPageSnapshot(
        requested_url=requested_url,
        final_url=parsed["final_url"],
        fetch_status=parsed["fetch_status"],
        content_type=parsed["content_type"],
        page_title=parsed["page_title"],
        visible_text_excerpt=parsed["visible_text_excerpt"],
        headings=parsed["headings"],
        links=parsed["links"],
        buttons=parsed["buttons"],
        forms=parsed["forms"],
        controls=parsed["controls"],
        embedded_json_summaries=parsed["embedded_json_summaries"],
        apply_link_candidates=candidates,
        job_identity_signals=_find_job_identity_signals(parsed, requested_url),
        raw_html_excerpt=parsed["raw_html_excerpt"],
        errors=parsed["errors"],
        browser_fallback_used=parsed["browser_fallback_used"],
    )


def _find_apply_link_candidates(
    links: list[JobPageLink],
    buttons: list[JobPageLink],
    source_url: str,
) -> list[JobPageLink]:
    candidates: list[JobPageLink] = []
    pattern = r"(?i)\b(apply|bewerb|application|karriereportal|online\s+bewerben)\b"
    for candidate in [*links, *buttons]:
        haystack = f"{candidate.text} {candidate.url} {' '.join(candidate.attributes.values())}"
        if not re.search(pattern, haystack):
            continue
        if candidate.url and not candidate.url.startswith(("http://", "https://")):
            continue
        if candidate.url:
            try:
                validate_apply_url(candidate.url, source_url)
            except ValueError:
                pass
        candidates.append(candidate)
    return candidates[:25]


def _find_job_identity_signals(parsed: dict[str, object], source_url: str) -> list[str]:
    signals: list[str] = []
    for heading in parsed.get("headings", []):
        if isinstance(heading, str) and heading:
            signals.append(f"heading: {heading}")
    if parsed.get("page_title"):
        signals.append(f"title: {parsed['page_title']}")
    final_url = str(parsed.get("final_url") or "")
    if final_url and final_url != source_url:
        signals.append(f"final_url: {final_url}")
    return signals[:20]


def extract_job_data_with_llm(source_url: str, snapshot: JobPageSnapshot) -> ExtractedJobData:
    normalized_url = _validate_source_url(source_url)
    client = _get_openai_client()
    snapshot_json = json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=True)

    response = client.responses.parse(
        model=MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You interpret a read-only JobPageSnapshot for a human-in-the-loop "
                    "job application workflow. The snapshot is the primary source of truth. "
                    "Do not browse. Focus only on job-offer facts supported by the snapshot.\n\n"
                    "Leave unknown fields empty. Do not invent salary, location, company, "
                    "posted date, job ID, requirements, or responsibilities.\n\n"
                    "Put application-relevant facts that do not fit the fixed schema into "
                    "dynamic_fields. For each dynamic field, create a concise name, value, "
                    "optional category, short source_text excerpt when available, and "
                    "confidence level.\n\n"
                    "Do not resolve apply_url here. Leave apply_url empty unless it is "
                    "directly and unambiguously visible in the job page text. A separate "
                    "resolver handles application URLs."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract application-preparation data from this selected job URL and "
                    "snapshot evidence.\n\n"
                    f"Source job URL: {normalized_url}\n\n"
                    f"JobPageSnapshot:\n{snapshot_json}"
                ),
            },
        ],
        text_format=ExtractedJobData,
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured job data.")

    return response.output_parsed


def extract_job_data_with_web_search_fallback(
    source_url: str,
    snapshot: JobPageSnapshot | None = None,
) -> ExtractedJobData:
    normalized_url = _validate_source_url(source_url)
    client = _get_openai_client()
    fallback_reason = ""
    if snapshot is not None:
        fallback_reason = (
            "; ".join(snapshot.errors) or "Local snapshot was too sparse or uncertain."
        )

    response = client.responses.parse(
        model=MODEL,
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": (
                    "You extract job-offer information from public job URLs for a "
                    "human-in-the-loop job application workflow.\n\n"
                    "Use web search/open-page capability because deterministic local "
                    "inspection was empty, blocked, JS-only, or too uncertain. Focus only "
                    "on the supplied job offer page and facts supported by that page.\n\n"
                    "Leave unknown fields empty. Do not invent salary, location, company, "
                    "posted date, job ID, requirements, or responsibilities. Do not resolve "
                    "apply_url here unless directly and unambiguously visible."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract application-preparation data from this job URL:\n"
                    f"{normalized_url}\n\n"
                    f"Fallback reason: {fallback_reason or 'snapshot unavailable'}"
                ),
            },
        ],
        text_format=ExtractedJobData,
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured job data.")

    return response.output_parsed


def resolve_apply_url_from_url(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
) -> ApplyUrlResolution:
    snapshot = inspect_job_page_agent(source_url)
    extracted = ExtractedJobData(title=title, company=company)
    resolution = resolve_apply_url_from_snapshot(source_url, snapshot, extracted)
    if resolution.status == "resolved" and resolution.apply_url:
        return resolution
    return resolve_apply_url_with_web_search_fallback(
        source_url,
        title=title,
        company=company,
        prior_resolution=resolution,
    )


def resolve_apply_url_from_snapshot(
    source_url: str,
    snapshot: JobPageSnapshot,
    extracted: ExtractedJobData,
) -> ApplyUrlResolution:
    normalized_url = _validate_source_url(source_url)
    candidates = [
        candidate
        for candidate in snapshot.apply_link_candidates
        if choose_valid_apply_url(normalized_url, candidate.url)
    ]
    if not candidates:
        return ApplyUrlResolution(
            status="not_found",
            notes="No usable apply-link candidate was visible in the local job page snapshot.",
            evidence=snapshot.job_identity_signals[:5],
            rejected_candidates=[
                RejectedApplyCandidate(
                    url=candidate.url,
                    reason="Candidate was missing, non-HTTP, or matched the source job page.",
                    evidence=candidate.text,
                )
                for candidate in snapshot.apply_link_candidates[:10]
                if not choose_valid_apply_url(normalized_url, candidate.url)
            ],
            confidence="low",
        )

    client = _get_openai_client()
    snapshot_payload = {
        "source_url": normalized_url,
        "final_url": snapshot.final_url,
        "page_title": snapshot.page_title,
        "headings": snapshot.headings,
        "job_identity_signals": snapshot.job_identity_signals,
        "visible_text_excerpt": snapshot.visible_text_excerpt,
        "apply_link_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    response = client.responses.parse(
        model=MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You choose the best job-preserving apply URL from deterministic "
                    "JobPageSnapshot evidence. Do not browse. Return only HTTP or HTTPS "
                    "URLs. Reject mailto links, contact pages, talent communities, generic "
                    "career pages, job alerts, and candidates that match the source job page."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Resolve the apply URL from the supplied snapshot evidence.\n\n"
                    f"Known title: {extracted.title or 'Unknown'}\n"
                    f"Known company: {extracted.company or 'Unknown'}\n\n"
                    f"Snapshot evidence:\n"
                    f"{json.dumps(snapshot_payload, indent=2, ensure_ascii=True)}"
                ),
            },
        ],
        text_format=ApplyUrlResolution,
    )
    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured apply URL data.")
    resolution = response.output_parsed
    if resolution.apply_url and not choose_valid_apply_url(normalized_url, resolution.apply_url):
        resolution.rejected_candidates.append(
            RejectedApplyCandidate(
                url=resolution.apply_url,
                reason="LLM-selected URL was not a distinct HTTP(S) apply destination.",
                evidence="Validated against source URL.",
            )
        )
        resolution.apply_url = ""
        resolution.status = "needs_review"
        resolution.confidence = "low"
    return resolution


def resolve_apply_url_with_web_search_fallback(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
    prior_resolution: ApplyUrlResolution | None = None,
) -> ApplyUrlResolution:
    normalized_url = _validate_source_url(source_url)
    client = _get_openai_client()
    prior_notes = prior_resolution.model_dump(mode="json") if prior_resolution else {}

    response = client.responses.parse(
        model=MODEL,
        tools=[_web_search_tool()],
        tool_choice={"type": "web_search"},
        input=[
            {
                "role": "system",
                "content": (
                    "You resolve the real application destination for a public job offer.\n\n"
                    "Use web search/open-page capability. Do not guess. You must inspect "
                    "the supplied job page and identify the actual URL a candidate reaches "
                    "to begin applying.\n\n"
                    "Important: do not trust the first apply-looking URL blindly. Some "
                    "pages expose intermediate URLs such as talent-community pages, tracking "
                    "links, job-alert pages, or URLs that redirect to generic career pages. "
                    "Those are not valid resolved apply URLs unless they preserve the same "
                    "job identity after opening.\n\n"
                    "Process:\n"
                    "1. Open or inspect the source job page.\n"
                    "2. Find links/buttons with labels such as Apply, Apply now, Bewerben, "
                    "Jetzt bewerben, Online bewerben, Zur Bewerbung, Application form, "
                    "Karriereportal, or equivalent wording.\n"
                    "3. For every plausible candidate, verify whether the candidate URL or "
                    "its opened/redirected destination still refers to the same job.\n"
                    "4. Prefer the final application URL that preserves the job identity.\n"
                    "5. Reject candidates that lose the job identity, redirect to a generic "
                    "career homepage, point to talent community signup, job alerts, saved "
                    "search, newsletter signup, generic login without job context, contact "
                    "page, mailto link, phone number, or the original job-description page.\n\n"
                    "Job identity can be preserved by any of these signals:\n"
                    "- same job title\n"
                    "- same company\n"
                    "- same location\n"
                    "- same requisition ID or job ID\n"
                    "- application URL contains a job/requisition parameter\n"
                    "- destination page clearly shows the same role\n\n"
                    "Return only HTTP or HTTPS URLs. Never return mailto links, email "
                    "addresses, phone numbers, contact-person URLs, or the original "
                    "job-description URL.\n\n"
                    "If two URLs point to the same application but one contains only tracking "
                    "parameters, prefer the cleaner URL when the job identity is still "
                    "preserved. If the tracking URL is the only verified URL, returning it is "
                    "acceptable.\n\n"
                    "If an apply button exists but the final job-preserving URL cannot be "
                    "verified, set status='needs_review' and leave apply_url empty.\n\n"
                    "If no application destination exists or the only action is email, set "
                    "status='not_found' or status='needs_review' and leave apply_url empty.\n\n"
                    "Use rejected_candidates to record plausible URLs that were rejected and "
                    "why. Use evidence for short facts that justify the final decision."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Resolve the real application URL for this job offer.\n\n"
                    f"Source job URL: {normalized_url}\n"
                    f"Known title: {title.strip() or 'Unknown'}\n"
                    f"Known company: {company.strip() or 'Unknown'}\n\n"
                    f"Local snapshot resolution result before fallback:\n"
                    f"{json.dumps(prior_notes, indent=2, ensure_ascii=True)}\n\n"
                    "Return the final job-preserving application URL. Do not return an "
                    "intermediate URL if it redirects to a generic career page or loses the "
                    "job identity."
                ),
            },
        ],
        text_format=ApplyUrlResolution,
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured apply URL data.")

    return response.output_parsed


def save_job_page_snapshot(
    base_dir: Path | str,
    job_id: str,
    snapshot: JobPageSnapshot,
) -> Path:
    target = Path(base_dir) / RUNTIME_DATA_DIR / "jobs" / job_id / JOB_PAGE_SNAPSHOT_FILENAME
    save_model(target, snapshot)
    return target
