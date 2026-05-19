from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.job_intake import validate_apply_url
from src.llm_job_extraction import MODEL, _get_openai_client
from src.page_inspection import (
    clip as _shared_clip,
)
from src.page_inspection import (
    fetch_page,
    page_needs_browser_fallback,
    parse_page_document,
)
from src.page_inspection import (
    redact as _shared_redact,
)
from src.schemas import (
    ApplicationFormField,
    ApplicationPageControl,
    ApplicationPageFormSummary,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    ConfidenceLevel,
    JobListing,
)
from src.storage import save_model

APPLICATION_REQUIREMENTS_FILENAME = "application_requirements.json"
APPLICATION_PAGE_SNAPSHOT_FILENAME = "application_page_snapshot.json"
RUNTIME_DATA_DIR = Path("data/runtime")
MAX_APPLY_PAGE_CHARS = 80_000
MAX_SNAPSHOT_TEXT_CHARS = 20_000
MAX_EVIDENCE_MATCHES = 80
MAX_EMBEDDED_JSON_ITEMS = 20

RequirementsExtractor = Callable[[JobListing, ApplicationPageSnapshot], ApplicationRequirements]
SnapshotInspector = Callable[[JobListing], ApplicationPageSnapshot]

SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(cookie|session|csrf|xsrf|token|authorization|auth|password|secret|api[_-]?key)"
    r"([\"'\s:=]+)([^\"'\s<>&]{6,})"
)
EVIDENCE_PATTERN = re.compile(
    r"\b("
    r"cv|resume|lebenslauf|cover\s*letter|motivation(?:sschreiben)?|anschreiben|"
    r"upload|hochladen|anhang|anlage|attachment|document|dokument|file|datei|"
    r"pdf|docx|max(?:imum)?\s*\d+|mb|consent|privacy|datenschutz|einwilligung|"
    r"screening|question|frage|required|pflicht|bewerbung|application|search\s+jobs|"
    r"talent\s+community|openings"
    r")\b",
    re.IGNORECASE,
)


class RequirementsDiscoveryState(TypedDict, total=False):
    job: JobListing
    page_content: str | None
    final_url: str | None
    inspector: SnapshotInspector | None
    extractor: RequirementsExtractor | None
    snapshot: ApplicationPageSnapshot
    requirements: ApplicationRequirements


class LLMApplicationRequirementsResponse(BaseModel):
    job_id: str
    apply_url: str
    source_url: str
    status: Literal["discovered", "blocked"] = "discovered"
    blocked_reason: str | None = None
    job_preserving: bool = False
    required_documents: list[ApplicationRequirementFinding] = Field(default_factory=list)
    upload_expectations: list[ApplicationRequirementFinding] = Field(default_factory=list)
    screening_questions: list[ApplicationScreeningQuestion] = Field(default_factory=list)
    custom_form_fields: list[ApplicationFormField] = Field(default_factory=list)
    profile_fields: list[ApplicationFormField] = Field(default_factory=list)
    motivation_letter: ApplicationRequirementFinding | None = None
    consent_requirements: list[ApplicationRequirementFinding] = Field(default_factory=list)
    privacy_login_ats_gates: list[ApplicationRequirementFinding] = Field(default_factory=list)
    deadlines: list[ApplicationRequirementFinding] = Field(default_factory=list)
    contact_or_fallback: list[ApplicationRequirementFinding] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "medium"


def discover_application_requirements(
    job: JobListing,
    *,
    page_content: str | None = None,
    final_url: str | None = None,
    extractor: RequirementsExtractor | None = None,
    inspector: SnapshotInspector | None = None,
) -> ApplicationRequirements:
    state = run_requirements_discovery_graph(
        job,
        page_content=page_content,
        final_url=final_url,
        extractor=extractor,
        inspector=inspector,
    )
    return state["requirements"]


def run_requirements_discovery_graph(
    job: JobListing,
    *,
    page_content: str | None = None,
    final_url: str | None = None,
    extractor: RequirementsExtractor | None = None,
    inspector: SnapshotInspector | None = None,
) -> RequirementsDiscoveryState:
    _validate_requirements_discovery_input(job)
    state: RequirementsDiscoveryState = {
        "job": job,
        "page_content": page_content,
        "final_url": final_url,
        "extractor": extractor,
        "inspector": inspector,
    }

    graph = build_requirements_discovery_graph()
    return graph.invoke(state)


def build_requirements_discovery_graph():
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialRequirementsGraph()

    graph = StateGraph(RequirementsDiscoveryState)
    graph.add_node("inspect_application_page_agent", _inspect_application_page_node)
    graph.add_node("extract_application_requirements", _extract_application_requirements_node)
    graph.set_entry_point("inspect_application_page_agent")
    graph.add_edge("inspect_application_page_agent", "extract_application_requirements")
    graph.add_edge("extract_application_requirements", END)
    return graph.compile()


class _SequentialRequirementsGraph:
    def invoke(self, state: RequirementsDiscoveryState) -> RequirementsDiscoveryState:
        next_state = dict(state)
        next_state.update(_inspect_application_page_node(next_state))
        next_state.update(_extract_application_requirements_node(next_state))
        return next_state


def _validate_requirements_discovery_input(job: JobListing) -> None:
    if not job.apply_url:
        raise ValueError("Apply URL is required before discovering application requirements.")
    validate_apply_url(str(job.apply_url), str(job.source_url))


def _inspect_application_page_node(
    state: RequirementsDiscoveryState,
) -> dict[str, ApplicationPageSnapshot]:
    job = state["job"]
    inspector = state.get("inspector")
    if inspector is not None:
        snapshot = inspector(job)
    else:
        snapshot = inspect_application_page_agent(
            job,
            page_content=state.get("page_content"),
            final_url=state.get("final_url"),
        )
    return {"snapshot": snapshot}


def _extract_application_requirements_node(
    state: RequirementsDiscoveryState,
) -> dict[str, ApplicationRequirements]:
    job = state["job"]
    extractor = state.get("extractor") or extract_application_requirements_with_llm
    requirements = extractor(job, state["snapshot"])
    return {"requirements": normalize_application_requirements(job, requirements)}


def inspect_application_page_agent(
    job: JobListing,
    *,
    page_content: str | None = None,
    final_url: str | None = None,
) -> ApplicationPageSnapshot:
    apply_url = str(job.apply_url)
    if page_content is not None:
        return build_application_page_snapshot(
            job,
            requested_url=apply_url,
            final_url=final_url or apply_url,
            html=page_content,
            fetch_status=200 if page_content else None,
            content_type="text/html",
            errors=[] if page_content else ["No local page content supplied."],
        )

    fetch_result = fetch_application_page(apply_url)
    snapshot = build_application_page_snapshot(job, **fetch_result)
    if _needs_browser_fallback(snapshot):
        browser_snapshot = inspect_application_page_with_browser(job, apply_url)
        if browser_snapshot is not None:
            return browser_snapshot
        snapshot.errors.append("Playwright browser fallback is unavailable or failed.")
    return snapshot


def fetch_application_page(url: str) -> dict[str, Any]:
    return fetch_page(url, byte_limit=MAX_APPLY_PAGE_CHARS)


def build_application_page_snapshot(
    job: JobListing,
    *,
    requested_url: str,
    final_url: str,
    html: str,
    fetch_status: int | None,
    content_type: str,
    errors: list[str] | None = None,
    browser_fallback_used: bool = False,
) -> ApplicationPageSnapshot:
    parsed = parse_page_document(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        fetch_status=fetch_status,
        content_type=content_type,
        errors=errors,
        browser_fallback_used=browser_fallback_used,
    )
    evidence = _extract_evidence_matches(parsed["raw_html_excerpt"], parsed["visible_text_excerpt"])
    job_signals = _find_job_preserving_signals(
        job,
        final_url,
        parsed["visible_text_excerpt"],
    )

    return ApplicationPageSnapshot(
        requested_url=requested_url,
        final_url=final_url or requested_url,
        fetch_status=fetch_status,
        content_type=content_type,
        page_title=parsed["page_title"],
        evidence_matches=evidence,
        forms=parsed["forms"],
        controls=parsed["controls"],
        embedded_json_summaries=parsed["embedded_json_summaries"],
        job_preserving_signals=job_signals,
        visible_text_excerpt=parsed["visible_text_excerpt"],
        raw_html_excerpt=parsed["raw_html_excerpt"],
        errors=parsed["errors"],
        browser_fallback_used=browser_fallback_used,
    )


def inspect_application_page_with_browser(
    job: JobListing,
    url: str,
) -> ApplicationPageSnapshot | None:
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

    return build_application_page_snapshot(
        job,
        requested_url=url,
        final_url=final_url,
        html=html,
        fetch_status=status,
        content_type=content_type,
        errors=[],
        browser_fallback_used=True,
    )


def _needs_browser_fallback(snapshot: ApplicationPageSnapshot) -> bool:
    return page_needs_browser_fallback(
        raw_html_excerpt=snapshot.raw_html_excerpt,
        visible_text_excerpt=snapshot.visible_text_excerpt,
        fetch_status=snapshot.fetch_status,
        has_interactive_elements=bool(snapshot.forms or snapshot.controls),
    )


def _parse_forms(soup: BeautifulSoup) -> list[ApplicationPageFormSummary]:
    forms: list[ApplicationPageFormSummary] = []
    for form in soup.find_all("form")[:20]:
        form_soup = BeautifulSoup(str(form), "html.parser")
        labels = [
            _clip(_redact(label.get_text(" ", strip=True)), 300)
            for label in form.find_all("label")
        ]
        buttons = [
            _clip(_redact(button.get_text(" ", strip=True) or button.get("value", "")), 200)
            for button in form.find_all(["button", "input"])
            if button.name == "button" or button.get("type") in {"button", "submit"}
        ]
        forms.append(
            ApplicationPageFormSummary(
                action=_redact(form.get("action", "")),
                method=(form.get("method", "get") or "get").lower(),
                labels=[label for label in labels if label],
                buttons=[button for button in buttons if button],
                controls=_parse_controls(form_soup),
            )
        )
    return forms


def _parse_controls(soup: BeautifulSoup) -> list[ApplicationPageControl]:
    controls: list[ApplicationPageControl] = []
    selectors = ["input", "select", "textarea", "button", "[role]", "[data-testid]", "[data-test]"]
    seen: set[str] = set()
    for element in soup.select(",".join(selectors))[:150]:
        fingerprint = str(element)[:500]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        kind = element.name or element.get("role", "")
        input_type = element.get("type", "") if element.name == "input" else element.name
        label = _control_label(element, soup)
        attrs = {
            key: _clip(_redact(" ".join(value) if isinstance(value, list) else str(value)), 300)
            for key, value in element.attrs.items()
            if key.startswith("data-")
            or key in {"accept", "aria-label", "placeholder", "name", "id"}
        }
        options = [
            _clip(_redact(option.get_text(" ", strip=True)), 200)
            for option in element.find_all("option")
        ]
        evidence = label or element.get("placeholder", "") or element.get("aria-label", "")
        controls.append(
            ApplicationPageControl(
                kind=kind,
                name=_redact(element.get("name", "")),
                label=_clip(_redact(label), 300),
                input_type=_redact(input_type or element.get("role", "")),
                required=element.has_attr("required") or element.get("aria-required") == "true",
                options=[option for option in options if option],
                attributes=attrs,
                evidence=_clip(_redact(evidence), 500),
            )
        )
    return controls


def _control_label(element: Any, soup: BeautifulSoup) -> str:
    labels: list[str] = []
    element_id = element.get("id")
    if element_id:
        for label in soup.find_all("label", attrs={"for": element_id}):
            labels.append(label.get_text(" ", strip=True))
    parent_label = element.find_parent("label")
    if parent_label is not None:
        labels.append(parent_label.get_text(" ", strip=True))
    for attr in ("aria-label", "placeholder", "name", "id", "data-testid", "data-test"):
        value = element.get(attr)
        if value:
            labels.append(str(value))
    return " ".join(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _parse_embedded_json(soup: BeautifulSoup) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for script in soup.find_all("script")[:80]:
        script_type = (script.get("type") or "").lower()
        text = script.string or script.get_text("", strip=False)
        if not text.strip():
            continue
        if "json" in script_type:
            parsed = _safe_json_loads(text)
            if parsed is not None:
                summaries.append(_summarize_json(parsed, script.get("id", "")))
        else:
            for match in re.finditer(
                r"({[^{}]*(?:upload|attachment|required|file)[^{}]*})",
                text,
                re.I,
            ):
                parsed = _safe_json_loads(match.group(1))
                if parsed is not None:
                    summaries.append(_summarize_json(parsed, script.get("id", "")))
        if len(summaries) >= MAX_EMBEDDED_JSON_ITEMS:
            break
    return summaries[:MAX_EMBEDDED_JSON_ITEMS]


def _safe_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _summarize_json(value: Any, source_id: str = "") -> dict[str, Any]:
    text = _clip(_redact(json.dumps(value, ensure_ascii=True, sort_keys=True)), 1200)
    keys: list[str] = []
    if isinstance(value, dict):
        keys = [str(key) for key in list(value.keys())[:30]]
    return {"source_id": _redact(source_id), "keys": keys, "summary": text}


def _extract_evidence_matches(html: str, visible_text: str) -> list[str]:
    html_text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    combined = f"{visible_text}\n{html_text}"
    sentences = re.split(r"(?<=[.!?])\s+|\n+", combined)
    matches: list[str] = []
    for sentence in sentences:
        clean = _clip(_redact(" ".join(sentence.split())), 500)
        if clean and EVIDENCE_PATTERN.search(clean):
            matches.append(clean)
        if len(matches) >= MAX_EVIDENCE_MATCHES:
            break
    return list(dict.fromkeys(matches))


def _find_job_preserving_signals(job: JobListing, final_url: str, visible_text: str) -> list[str]:
    signals: list[str] = []
    haystack = f"{final_url}\n{visible_text}".lower()
    for label, value in (
        ("title", job.title),
        ("company", job.company),
        ("source_job_id", job.source_job_id or ""),
    ):
        if value and str(value).lower() in haystack:
            signals.append(f"{label}: {value}")
    return signals


def _redact(value: str) -> str:
    return _shared_redact(value)


def _clip(value: str, limit: int) -> str:
    return _shared_clip(value, limit)


def normalize_application_requirements(
    job: JobListing,
    requirements: ApplicationRequirements,
) -> ApplicationRequirements:
    payload = requirements.model_dump(mode="json", warnings=False)
    payload.update(
        {
            "job_id": job.id,
            "apply_url": str(job.apply_url),
            "source_url": str(job.source_url),
        }
    )
    normalized = ApplicationRequirements.model_validate(payload)
    if normalized.status == "discovered" and not normalized.job_preserving:
        normalized.status = "blocked"
        normalized.blocked_reason = (
            normalized.blocked_reason
            or "Apply page does not preserve the selected job identity."
        )
    return normalized


def extract_application_requirements_with_llm(
    job: JobListing,
    snapshot: ApplicationPageSnapshot,
) -> ApplicationRequirements:
    client = _get_openai_client()
    apply_url = str(job.apply_url)
    snapshot_json = json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=True)

    try:
        response = client.responses.parse(
            model=MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You interpret a read-only ApplicationPageSnapshot for a controlled, "
                        "human-in-the-loop job application workflow. The snapshot is the "
                        "primary source of truth. Do not browse, submit forms, upload files, "
                        "log in, enter personal data, or infer requirements from hiring norms.\n\n"
                        "Extract only requirements supported by snapshot evidence: documents, "
                        "upload constraints, screening questions, requested profile fields, "
                        "custom fields, motivation or cover letter needs, consent requirements, "
                        "privacy/login/ATS gates, deadlines, contact/fallback information, "
                        "missing or uncertain items, source evidence, job preservation, and "
                        "confidence.\n\n"
                        "If the snapshot is empty, blocked, generic, not job-preserving, or too "
                        "uncertain, return status='blocked' or list missing_or_uncertain items. "
                        "Never invent requirements that are not visible in the snapshot."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Discover application requirements for this selected job from the "
                        "snapshot evidence.\n\n"
                        f"Internal job ID: {job.id}\n"
                        f"Job title: {job.title}\n"
                        f"Company: {job.company}\n"
                        f"Source job URL: {job.source_url}\n"
                        f"Verified apply URL: {apply_url}\n"
                        f"Source job ID: {job.source_job_id or 'Unknown'}\n\n"
                        f"ApplicationPageSnapshot:\n{snapshot_json}"
                    ),
                },
            ],
            text_format=LLMApplicationRequirementsResponse,
        )
    except Exception as exc:
        raise RuntimeError(f"AI application requirements extraction failed: {exc}") from exc

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured application requirements.")

    payload = response.output_parsed.model_dump(mode="json")
    payload.update(
        {
            "job_id": job.id,
            "apply_url": apply_url,
            "source_url": str(job.source_url),
        }
    )
    return ApplicationRequirements.model_validate(payload)


def save_application_page_snapshot(
    base_dir: Path | str,
    job_id: str,
    snapshot: ApplicationPageSnapshot,
) -> Path:
    target = (
        Path(base_dir)
        / RUNTIME_DATA_DIR
        / "jobs"
        / job_id
        / APPLICATION_PAGE_SNAPSHOT_FILENAME
    )
    save_model(target, snapshot)
    return target


def save_application_requirements(
    base_dir: Path | str,
    requirements: ApplicationRequirements,
) -> Path:
    target = (
        Path(base_dir)
        / RUNTIME_DATA_DIR
        / "jobs"
        / requirements.job_id
        / APPLICATION_REQUIREMENTS_FILENAME
    )
    save_model(target, requirements)
    return target
