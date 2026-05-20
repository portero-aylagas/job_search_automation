from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal, TypedDict
from urllib.parse import parse_qsl, urldefrag, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src import llm_client
from src.llm_job_extraction import (
    ApplyUrlResolution,
    RejectedApplyCandidate,
    resolve_apply_url_from_url,
)
from src.url_validation import validate_source_url

MAX_SOURCE_PAGE_CHARS = 100_000
MAX_CANDIDATE_PAGE_CHARS = 60_000
MAX_LLM_EVIDENCE_CHARS = 24_000
MAX_CANDIDATES = 40

APPLY_KEYWORDS = (
    "apply",
    "apply now",
    "application",
    "submit application",
    "bewerben",
    "jetzt bewerben",
    "online bewerben",
    "zur bewerbung",
    "candidatura",
    "postular",
    "solicitar",
    "career portal",
    "karriereportal",
)

REJECT_KEYWORDS = (
    "newsletter",
    "job alert",
    "jobalert",
    "saved search",
    "talent community",
    "join our talent",
    "privacy",
    "datenschutz",
    "contact",
    "kontakt",
    "imprint",
    "impressum",
    "share",
)
HARD_REJECT_KEYWORDS = (
    "newsletter",
    "job alert",
    "jobalert",
    "saved search",
    "talent community",
    "join our talent",
)

DATA_URL_ATTRIBUTES = (
    "data-url",
    "data-href",
    "data-apply-url",
    "data-apply-href",
    "data-target-url",
    "data-link",
)

APPLY_PATTERN = re.compile("|".join(re.escape(keyword) for keyword in APPLY_KEYWORDS), re.I)
REJECT_PATTERN = re.compile("|".join(re.escape(keyword) for keyword in REJECT_KEYWORDS), re.I)
HARD_REJECT_PATTERN = re.compile(
    "|".join(re.escape(keyword) for keyword in HARD_REJECT_KEYWORDS),
    re.I,
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\]+|/[A-Za-z0-9][^\s\"'<>\\]*")
ONCLICK_URL_PATTERN = re.compile(
    r"(?:location(?:\.href)?|window\.open)\s*\(?\s*['\"]([^'\"]+)['\"]",
    re.I,
)
JOB_PARAM_PATTERN = re.compile(
    r"(?i)(job|jobid|job_id|jid|requisition|req|posting|position|gh_jid)"
)


class ApplyUrlCandidate(BaseModel):
    url: str
    source: Literal[
        "href",
        "button",
        "form_action",
        "onclick",
        "data_attribute",
        "embedded_json",
        "llm_suggested",
    ]
    label: str = ""
    evidence: str = ""
    final_url: str = ""
    status: Literal["candidate", "verified", "rejected"] = "candidate"
    rejection_reason: str = ""
    job_preserving_signals: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class FetchResult(TypedDict, total=False):
    requested_url: str
    final_url: str
    html: str
    status_code: int | None
    content_type: str
    errors: list[str]


class CandidateExtractionResult(TypedDict):
    candidates: list[ApplyUrlCandidate]
    rejected_candidates: list[RejectedApplyCandidate]


class ApplyUrlResolutionState(TypedDict, total=False):
    source_url: str
    title: str
    company: str
    source_job_id: str
    html: str
    final_source_url: str
    fetch_status: int | None
    candidates: list[ApplyUrlCandidate]
    verified_candidates: list[ApplyUrlCandidate]
    rejected_candidates: list[RejectedApplyCandidate]
    candidate_discovery_mode: Literal[
        "static_candidates_found",
        "llm_fallback_candidate_found",
        "no_candidates_at_all",
    ]
    resolution: ApplyUrlResolution
    errors: list[str]
    fetcher: Callable[[str], FetchResult] | None
    ranker: Callable[["ApplyUrlResolutionState"], ApplyUrlResolution] | None


def resolve_apply_url_agentically(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
    source_job_id: str = "",
    page_content: str | None = None,
    final_source_url: str | None = None,
    fetcher: Callable[[str], FetchResult] | None = None,
    ranker: Callable[[ApplyUrlResolutionState], ApplyUrlResolution] | None = None,
) -> ApplyUrlResolution:
    state = run_apply_url_resolution_graph(
        source_url,
        title=title,
        company=company,
        source_job_id=source_job_id,
        page_content=page_content,
        final_source_url=final_source_url,
        fetcher=fetcher,
        ranker=ranker,
    )
    return state["resolution"]


def run_apply_url_resolution_graph(
    source_url: str,
    *,
    title: str = "",
    company: str = "",
    source_job_id: str = "",
    page_content: str | None = None,
    final_source_url: str | None = None,
    fetcher: Callable[[str], FetchResult] | None = None,
    ranker: Callable[[ApplyUrlResolutionState], ApplyUrlResolution] | None = None,
) -> ApplyUrlResolutionState:
    normalized_url = validate_source_url(source_url)
    state: ApplyUrlResolutionState = {
        "source_url": normalized_url,
        "title": title.strip(),
        "company": company.strip(),
        "source_job_id": source_job_id.strip(),
        "final_source_url": final_source_url or normalized_url,
        "errors": [],
        "fetcher": fetcher,
        "ranker": ranker,
    }
    if page_content is not None:
        state["html"] = page_content
        state["fetch_status"] = 200 if page_content else None

    graph = build_apply_url_resolution_graph()
    return graph.invoke(state)


def build_apply_url_resolution_graph():
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialApplyUrlResolutionGraph()

    graph = StateGraph(ApplyUrlResolutionState)
    graph.add_node("fetch_source_page", _fetch_source_page_node)
    graph.add_node("extract_apply_url_candidates", _extract_candidates_node)
    graph.add_node("verify_apply_url_candidates", _verify_candidates_node)
    graph.add_node("rank_apply_url_candidates", _rank_candidates_node)
    graph.set_entry_point("fetch_source_page")
    graph.add_edge("fetch_source_page", "extract_apply_url_candidates")
    graph.add_edge("extract_apply_url_candidates", "verify_apply_url_candidates")
    graph.add_edge("verify_apply_url_candidates", "rank_apply_url_candidates")
    graph.add_edge("rank_apply_url_candidates", END)
    return graph.compile()


class _SequentialApplyUrlResolutionGraph:
    def invoke(self, state: ApplyUrlResolutionState) -> ApplyUrlResolutionState:
        next_state = dict(state)
        next_state.update(_fetch_source_page_node(next_state))
        next_state.update(_extract_candidates_node(next_state))
        next_state.update(_verify_candidates_node(next_state))
        next_state.update(_rank_candidates_node(next_state))
        return next_state


def _fetch_source_page_node(state: ApplyUrlResolutionState) -> dict[str, Any]:
    if "html" in state:
        return {
            "html": state.get("html", ""),
            "final_source_url": state.get("final_source_url") or state["source_url"],
        }

    result = fetch_html(state["source_url"], max_chars=MAX_SOURCE_PAGE_CHARS)
    errors = [*state.get("errors", []), *result.get("errors", [])]
    return {
        "html": result.get("html", ""),
        "final_source_url": result.get("final_url") or state["source_url"],
        "fetch_status": result.get("status_code"),
        "errors": errors,
    }


def _extract_candidates_node(state: ApplyUrlResolutionState) -> dict[str, Any]:
    result = extract_apply_url_candidates(
        state.get("html", ""),
        state["source_url"],
        final_source_url=state.get("final_source_url", ""),
    )
    candidates = list(result["candidates"])
    rejected_candidates = [
        *state.get("rejected_candidates", []),
        *result["rejected_candidates"],
    ]
    if candidates:
        return {
            "candidates": candidates,
            "rejected_candidates": rejected_candidates,
            "candidate_discovery_mode": "static_candidates_found",
        }

    llm_candidate, fallback_rejected, fallback_errors = _llm_fallback_candidate(state)
    rejected_candidates.extend(fallback_rejected)
    if llm_candidate is not None:
        return {
            "candidates": [llm_candidate],
            "rejected_candidates": rejected_candidates,
            "candidate_discovery_mode": "llm_fallback_candidate_found",
            "errors": [*state.get("errors", []), *fallback_errors],
        }

    return {
        "candidates": [],
        "rejected_candidates": rejected_candidates,
        "candidate_discovery_mode": "no_candidates_at_all",
        "errors": [*state.get("errors", []), *fallback_errors],
    }


def _verify_candidates_node(state: ApplyUrlResolutionState) -> dict[str, Any]:
    verified, rejected = verify_apply_url_candidates(
        state.get("candidates", []),
        source_url=state["source_url"],
        title=state.get("title", ""),
        company=state.get("company", ""),
        source_job_id=state.get("source_job_id", ""),
        fetcher=state.get("fetcher"),
    )
    return {
        "candidates": verified,
        "verified_candidates": [
            candidate for candidate in verified if candidate.status == "verified"
        ],
        "rejected_candidates": [*state.get("rejected_candidates", []), *rejected],
    }


def _rank_candidates_node(state: ApplyUrlResolutionState) -> dict[str, Any]:
    ranker = state.get("ranker")
    if ranker is not None:
        resolution = ranker(state)
    else:
        try:
            resolution = rank_apply_url_candidates_with_llm(state)
        except RuntimeError as exc:
            fallback = choose_apply_url_deterministically(state)
            fallback.notes = (
                f"{fallback.notes} LLM ranking was unavailable: {exc}"
                if fallback.notes
                else f"LLM ranking was unavailable: {exc}"
            )
            errors = [*state.get("errors", []), str(exc)]
            return {"resolution": fallback, "errors": errors}

    return {"resolution": normalize_apply_url_resolution(state, resolution)}


def extract_apply_url_candidates(
    html: str,
    source_url: str,
    *,
    final_source_url: str = "",
) -> CandidateExtractionResult:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[ApplyUrlCandidate] = []
    rejected: list[RejectedApplyCandidate] = []

    for anchor in soup.find_all("a", href=True):
        label = _element_label(anchor)
        evidence = _element_evidence(anchor)
        if _has_apply_context(label, evidence, anchor["href"]):
            _append_candidate_or_rejection(
                candidates,
                rejected,
                raw_url=anchor["href"],
                source_url=source_url,
                final_source_url=final_source_url,
                source="href",
                label=label,
                evidence=evidence,
            )

    for form in soup.find_all("form", action=True):
        label = _element_label(form)
        evidence = _element_evidence(form)
        if _has_apply_context(label, evidence, form["action"]):
            _append_candidate_or_rejection(
                candidates,
                rejected,
                raw_url=form["action"],
                source_url=source_url,
                final_source_url=final_source_url,
                source="form_action",
                label=label,
                evidence=evidence,
            )

    for element in soup.find_all(["button", "a", "div", "span"]):
        label = _element_label(element)
        evidence = _element_evidence(element)
        if not _has_apply_context(label, evidence, ""):
            continue
        for attr_name, raw_url in _extract_element_urls(element):
            if attr_name == "onclick":
                source = "onclick"
            elif element.name == "button" or attr_name == "formaction":
                source = "button"
            else:
                source = "data_attribute"
            _append_candidate_or_rejection(
                candidates,
                rejected,
                raw_url=raw_url,
                source_url=source_url,
                final_source_url=final_source_url,
                source=source,
                label=label,
                evidence=f"{attr_name}: {evidence}",
            )

    for raw_url, evidence in _extract_script_urls(soup):
        _append_candidate_or_rejection(
            candidates,
            rejected,
            raw_url=raw_url,
            source_url=source_url,
            final_source_url=final_source_url,
            source="embedded_json",
            label="embedded apply URL",
            evidence=evidence,
        )

    return {
        "candidates": _dedupe_candidates(candidates)[:MAX_CANDIDATES],
        "rejected_candidates": _dedupe_rejections(rejected),
    }


def verify_apply_url_candidates(
    candidates: list[ApplyUrlCandidate],
    *,
    source_url: str,
    title: str = "",
    company: str = "",
    source_job_id: str = "",
    fetcher: Callable[[str], FetchResult] | None = None,
) -> tuple[list[ApplyUrlCandidate], list[RejectedApplyCandidate]]:
    verified_candidates: list[ApplyUrlCandidate] = []
    rejected: list[RejectedApplyCandidate] = []
    fetch = fetcher or (lambda url: fetch_html(url, max_chars=MAX_CANDIDATE_PAGE_CHARS))

    for candidate in candidates[:MAX_CANDIDATES]:
        normalized_url = normalize_candidate_url(candidate.url, source_url)
        candidate = candidate.model_copy(update={"url": normalized_url})
        pre_rejection = rejection_reason_for_url(
            normalized_url,
            source_url=source_url,
            final_source_url="",
            evidence=f"{candidate.label} {candidate.evidence}",
        )
        if pre_rejection:
            verified_candidates.append(
                candidate.model_copy(
                    update={"status": "rejected", "rejection_reason": pre_rejection}
                )
            )
            rejected.append(
                RejectedApplyCandidate(
                    url=normalized_url,
                    reason=pre_rejection,
                    evidence=candidate.evidence or candidate.label,
                )
            )
            continue

        result = fetch(normalized_url)
        final_url = result.get("final_url") or normalized_url
        html = result.get("html", "")
        status_code = result.get("status_code")
        errors = result.get("errors", [])
        visible_text = html_to_visible_text(html)
        signals = find_job_preserving_signals(
            title=title,
            company=company,
            source_job_id=source_job_id,
            source_url=source_url,
            candidate_url=normalized_url,
            final_url=final_url,
            visible_text=visible_text,
        )

        if errors:
            reason = "; ".join(errors)
        elif status_code is not None and status_code >= 400:
            reason = f"HTTP fetch returned status {status_code}."
        elif is_generic_or_blocked_destination(final_url, visible_text, candidate.evidence):
            reason = "Destination appears generic or non-application related."
        elif same_url_identity(final_url, source_url):
            reason = "Candidate resolves to the source job-description URL."
        elif not signals:
            reason = "Destination did not preserve the selected job identity."
        else:
            reason = ""

        if reason:
            updated = candidate.model_copy(
                update={
                    "final_url": final_url,
                    "status": "rejected",
                    "rejection_reason": reason,
                    "job_preserving_signals": signals,
                    "confidence": "low",
                }
            )
            rejected.append(
                RejectedApplyCandidate(
                    url=normalized_url,
                    reason=reason,
                    evidence=_candidate_verification_evidence(
                        candidate,
                        final_url=final_url,
                        status_code=status_code,
                        signals=signals,
                    ),
                )
            )
        else:
            updated = candidate.model_copy(
                update={
                    "final_url": final_url,
                    "status": "verified",
                    "job_preserving_signals": signals,
                    "confidence": _verified_confidence(signals, candidate),
                }
            )
        verified_candidates.append(updated)

    return verified_candidates, _dedupe_rejections(rejected)


def fetch_html(url: str, *, max_chars: int) -> FetchResult:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8,de;q=0.7,es;q=0.6",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True, stream=True)
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            clipped = chunk[:remaining]
            chunks.append(clipped)
            total += len(clipped)
        response.close()
        encoding = response.encoding or "utf-8"
        html = b"".join(chunks).decode(encoding, errors="replace")
        return {
            "requested_url": url,
            "final_url": response.url or url,
            "html": html,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "errors": (
                [] if response.ok else [f"HTTP fetch returned status {response.status_code}."]
            ),
        }
    except requests.RequestException as exc:
        return {
            "requested_url": url,
            "final_url": url,
            "html": "",
            "status_code": None,
            "content_type": "",
            "errors": [f"HTTP fetch failed: {exc.__class__.__name__}: {exc}"],
        }


def rank_apply_url_candidates_with_llm(state: ApplyUrlResolutionState) -> ApplyUrlResolution:
    if not state.get("candidates"):
        return no_candidate_resolution(state)

    evidence_payload = {
        "source_url": state["source_url"],
        "final_source_url": state.get("final_source_url", ""),
        "title": state.get("title", ""),
        "company": state.get("company", ""),
        "source_job_id": state.get("source_job_id", ""),
        "candidates": [
            candidate.model_dump(mode="json")
            for candidate in state.get("candidates", [])
        ],
        "verified_candidates": [
            candidate.model_dump(mode="json")
            for candidate in state.get("verified_candidates", [])
        ],
        "rejected_candidates": [
            rejected.model_dump(mode="json")
            for rejected in state.get("rejected_candidates", [])
        ],
        "fetch_errors": state.get("errors", []),
    }
    evidence_json = _clip(
        json.dumps(evidence_payload, indent=2, ensure_ascii=True),
        MAX_LLM_EVIDENCE_CHARS,
    )

    return llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": (
                    "You rank collected apply URL candidates for a bounded, controlled "
                    "job-application discovery workflow. You do not browse, log in, "
                    "submit forms, upload files, enter personal data, or invent unseen "
                    "URLs.\n\n"
                    "Use only the supplied candidate and verification evidence. Return "
                    "status='resolved' only when a candidate is verified and clearly "
                    "preserves the selected job identity. Return needs_review when an "
                    "apply-like candidate exists but verification is uncertain. Return "
                    "not_found when no plausible application destination was found.\n\n"
                    "Never choose mailto, tel, social share, newsletter, job alert, saved "
                    "search, talent-community, contact/privacy/imprint pages, the source "
                    "job-description URL, or generic career pages that lost job identity."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Choose the best job-preserving application URL from this evidence.\n\n"
                    f"{evidence_json}"
                ),
            },
        ],
        text_format=ApplyUrlResolution,
        operation="AI apply URL ranking",
    )


def choose_apply_url_deterministically(state: ApplyUrlResolutionState) -> ApplyUrlResolution:
    verified = state.get("verified_candidates", [])
    rejected = state.get("rejected_candidates", [])
    if verified:
        best = sorted(
            verified,
            key=lambda candidate: (
                {"high": 3, "medium": 2, "low": 1}[candidate.confidence],
                len(candidate.job_preserving_signals),
                _has_apply_context(candidate.label, candidate.evidence, candidate.url),
            ),
            reverse=True,
        )[0]
        return ApplyUrlResolution(
            status="resolved",
            apply_url=best.final_url or best.url,
            notes="Selected the highest-confidence verified candidate from collected evidence.",
            evidence=[
                _candidate_verification_evidence(
                    best,
                    final_url=best.final_url,
                    status_code=None,
                    signals=best.job_preserving_signals,
                )
            ],
            rejected_candidates=rejected,
            confidence=best.confidence,
        )

    if state.get("candidates"):
        return ApplyUrlResolution(
            status="needs_review",
            apply_url="",
            notes="Apply-like candidates were found, but none preserved the selected job identity.",
            evidence=[
                f"Candidates inspected: {len(state.get('candidates', []))}",
                *state.get("errors", []),
            ],
            rejected_candidates=rejected,
            confidence="low",
        )

    return no_candidate_resolution(state)


def no_candidate_resolution(state: ApplyUrlResolutionState) -> ApplyUrlResolution:
    return ApplyUrlResolution(
        status="not_found",
        apply_url="",
        notes=_no_candidate_notes(state),
        evidence=[*state.get("errors", [])],
        rejected_candidates=state.get("rejected_candidates", []),
        confidence="low",
    )


def normalize_apply_url_resolution(
    state: ApplyUrlResolutionState,
    resolution: ApplyUrlResolution,
) -> ApplyUrlResolution:
    if resolution.status != "resolved":
        return resolution

    apply_url = resolution.apply_url.strip()
    verified_urls = {
        candidate.final_url or candidate.url
        for candidate in state.get("verified_candidates", [])
    }
    verified_urls.update(candidate.url for candidate in state.get("verified_candidates", []))
    if (
        apply_url
        and apply_url in verified_urls
        and not same_url_identity(apply_url, state["source_url"])
    ):
        return resolution

    return ApplyUrlResolution(
        status="needs_review",
        apply_url="",
        notes=(
            "The ranking step selected a URL that was not among the verified "
            "job-preserving candidates."
        ),
        evidence=[*resolution.evidence, f"Rejected ranked URL: {apply_url}"],
        rejected_candidates=[
            *resolution.rejected_candidates,
            RejectedApplyCandidate(
                url=apply_url,
                reason="Ranked URL was not verified by the deterministic workflow.",
                evidence="Only verified workflow candidates can be resolved automatically.",
            ),
        ],
        confidence="low",
    )


def normalize_candidate_url(raw_url: str, source_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return ""
    joined = urljoin(source_url, url)
    cleaned, _fragment = urldefrag(joined)
    return cleaned


def rejection_reason_for_url(
    raw_url: str,
    *,
    source_url: str,
    final_source_url: str = "",
    evidence: str = "",
) -> str:
    normalized = normalize_candidate_url(raw_url, source_url)
    parsed = urlsplit(normalized)
    lowered_url = normalized.lower()
    lowered_evidence = evidence.lower()

    if not normalized:
        return "Candidate URL is empty."
    if parsed.scheme in {"mailto", "tel"} or raw_url.strip().lower().startswith(
        ("mailto:", "tel:")
    ):
        return "Candidate is an email or phone link, not an application URL."
    if parsed.scheme not in {"http", "https"}:
        return "Candidate is not an HTTP or HTTPS URL."
    if same_url_identity(normalized, source_url) or (
        final_source_url and same_url_identity(normalized, final_source_url)
    ):
        return "Candidate matches the source job-description URL."
    if _is_social_share_url(lowered_url):
        return "Candidate is a social sharing URL."
    combined = f"{lowered_url} {lowered_evidence}"
    if "talent" in lowered_url and "community" in lowered_url:
        return "Candidate points to a talent-community signup."
    if HARD_REJECT_PATTERN.search(combined):
        return "Candidate points to a non-application destination."
    if REJECT_PATTERN.search(combined) and not APPLY_PATTERN.search(combined):
        return "Candidate points to a non-application destination."
    return ""


def find_job_preserving_signals(
    *,
    title: str = "",
    company: str = "",
    source_job_id: str = "",
    source_url: str = "",
    candidate_url: str = "",
    final_url: str = "",
    visible_text: str = "",
) -> list[str]:
    signals: list[str] = []
    haystack = f"{candidate_url}\n{final_url}\n{visible_text}".lower()
    for label, value in (
        ("title", title),
        ("company", company),
        ("source_job_id", source_job_id),
    ):
        normalized_value = value.strip()
        if normalized_value and normalized_value.lower() in haystack:
            signals.append(f"{label}: {normalized_value}")

    if source_url:
        shared_tokens = sorted(
            _identity_tokens(source_url) & _identity_tokens(f"{candidate_url} {final_url}")
        )
        if shared_tokens:
            signals.append(f"source URL job token: {shared_tokens[0]}")

    if _has_job_parameter(candidate_url) or _has_job_parameter(final_url):
        signals.append("job/requisition parameter in URL")

    return list(dict.fromkeys(signals))


def html_to_visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.extract()
    return soup.get_text(" ", strip=True)


def same_url_identity(first: str, second: str) -> bool:
    first_parsed = urlsplit(first.strip())
    second_parsed = urlsplit(second.strip())
    first_path = first_parsed.path.rstrip("/") or "/"
    second_path = second_parsed.path.rstrip("/") or "/"
    return (
        first_parsed.scheme.lower(),
        first_parsed.netloc.lower(),
        first_path,
    ) == (
        second_parsed.scheme.lower(),
        second_parsed.netloc.lower(),
        second_path,
    )


def is_generic_or_blocked_destination(final_url: str, visible_text: str, evidence: str) -> bool:
    combined = f"{final_url} {visible_text[:3000]} {evidence}".lower()
    generic_signals = (
        "talent community",
        "join our talent",
        "job alert",
        "saved search",
        "newsletter",
        "privacy policy",
        "impressum",
        "contact us",
    )
    if any(signal in combined for signal in generic_signals):
        return True

    parsed = urlsplit(final_url)
    generic_paths = {"/careers", "/career", "/jobs", "/stellenangebote", "/karriere"}
    return parsed.path.rstrip("/").lower() in generic_paths


def _append_candidate_or_rejection(
    candidates: list[ApplyUrlCandidate],
    rejected: list[RejectedApplyCandidate],
    *,
    raw_url: str,
    source_url: str,
    final_source_url: str,
    source: Literal[
        "href",
        "button",
        "form_action",
        "onclick",
        "data_attribute",
        "embedded_json",
        "llm_suggested",
    ],
    label: str,
    evidence: str,
) -> None:
    normalized_url = normalize_candidate_url(raw_url, source_url)
    reason = rejection_reason_for_url(
        normalized_url,
        source_url=source_url,
        final_source_url=final_source_url,
        evidence=f"{label} {evidence}",
    )
    if reason:
        rejected.append(
            RejectedApplyCandidate(
                url=normalized_url or raw_url,
                reason=reason,
                evidence=_clip(f"{label} {evidence}".strip(), 500),
            )
        )
        return

    candidates.append(
        ApplyUrlCandidate(
            url=normalized_url,
            source=source,
            label=_clip(label, 200),
            evidence=_clip(evidence, 500),
            confidence=_candidate_initial_confidence(normalized_url, label, evidence),
        )
    )


def _llm_fallback_candidate(
    state: ApplyUrlResolutionState,
) -> tuple[ApplyUrlCandidate | None, list[RejectedApplyCandidate], list[str]]:
    rejected: list[RejectedApplyCandidate] = []
    try:
        resolution = resolve_apply_url_from_url(
            state["source_url"],
            title=state.get("title", ""),
            company=state.get("company", ""),
        )
    except Exception as exc:
        return None, [], [f"LLM fallback candidate generation failed: {exc}"]

    fallback_url = resolution.apply_url.strip()
    if not fallback_url:
        return None, [], []

    candidates: list[ApplyUrlCandidate] = []
    evidence_parts = [resolution.notes.strip(), *resolution.evidence]
    _append_candidate_or_rejection(
        candidates,
        rejected,
        raw_url=fallback_url,
        source_url=state["source_url"],
        final_source_url=state.get("final_source_url", ""),
        source="llm_suggested",
        label="LLM-suggested apply URL",
        evidence=_clip(" | ".join(part for part in evidence_parts if part), 500),
    )
    if candidates:
        return candidates[0], rejected, []
    return None, rejected, []


def _extract_element_urls(element: Any) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    onclick = element.get("onclick")
    if onclick:
        urls.extend(("onclick", match.group(1)) for match in ONCLICK_URL_PATTERN.finditer(onclick))
    formaction = element.get("formaction")
    if formaction:
        urls.append(("formaction", str(formaction)))
    for attr_name in DATA_URL_ATTRIBUTES:
        value = element.get(attr_name)
        if value:
            urls.append((attr_name, str(value)))
    for attr_name in ("data-testid", "data-test"):
        value = element.get(attr_name)
        if value and _looks_like_url(str(value)):
            urls.append((attr_name, str(value)))
    return urls


def _extract_script_urls(soup: BeautifulSoup) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for script in soup.find_all("script")[:80]:
        text = script.string or script.get_text("", strip=False)
        if not text or not APPLY_PATTERN.search(text):
            continue
        for match in URL_PATTERN.finditer(text):
            raw_url = match.group(0).rstrip(".,);]")
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 180)
            context = " ".join(text[start:end].split())
            if APPLY_PATTERN.search(context):
                matches.append((raw_url, _clip(context, 500)))
        if len(matches) >= MAX_CANDIDATES:
            break
    return matches[:MAX_CANDIDATES]


def _element_label(element: Any) -> str:
    labels: list[str] = []
    text = element.get_text(" ", strip=True)
    if text:
        labels.append(text)
    for attr in ("aria-label", "title", "value", "name", "id", "data-testid", "data-test"):
        value = element.get(attr)
        if value:
            labels.append(str(value))
    return " ".join(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _element_evidence(element: Any) -> str:
    attrs = []
    for key, value in element.attrs.items():
        if key in {"class", "style"}:
            continue
        rendered = " ".join(value) if isinstance(value, list) else str(value)
        attrs.append(f"{key}={rendered}")
    text = element.get_text(" ", strip=True)
    return _clip(" ".join([text, *attrs]).strip(), 700)


def _has_apply_context(*values: str) -> bool:
    return bool(APPLY_PATTERN.search(" ".join(value for value in values if value)))


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "/"))


def _candidate_initial_confidence(
    url: str,
    label: str,
    evidence: str,
) -> Literal["high", "medium", "low"]:
    has_apply_label = _has_apply_context(label, evidence)
    url_has_apply = _has_apply_context(url)
    if has_apply_label and url_has_apply:
        return "high"
    if has_apply_label or url_has_apply:
        return "medium"
    return "low"


def _verified_confidence(
    signals: list[str],
    candidate: ApplyUrlCandidate,
) -> Literal["high", "medium", "low"]:
    if any(signal.startswith(("title:", "source_job_id:")) for signal in signals):
        return "high"
    if len(signals) >= 2 or candidate.confidence == "high":
        return "medium"
    return "low"


def _candidate_verification_evidence(
    candidate: ApplyUrlCandidate,
    *,
    final_url: str,
    status_code: int | None,
    signals: list[str],
) -> str:
    parts = [
        f"{candidate.source}: {candidate.label or candidate.url}",
        f"candidate_url={candidate.url}",
        f"final_url={final_url}",
    ]
    if status_code is not None:
        parts.append(f"http_status={status_code}")
    if signals:
        parts.append("signals=" + "; ".join(signals))
    if candidate.evidence:
        parts.append(f"evidence={candidate.evidence}")
    return _clip(" | ".join(parts), 1000)


def _no_candidate_notes(state: ApplyUrlResolutionState) -> str:
    mode = state.get("candidate_discovery_mode")
    if mode == "llm_fallback_candidate_found":
        return (
            "Only the LLM fallback produced an apply-like candidate, but deterministic "
            "verification rejected it."
        )
    if mode == "no_candidates_at_all":
        return (
            "No plausible application URL candidate was found on the source job page or "
            "through the fallback candidate generator."
        )
    return "No plausible application URL candidate was found on the source job page."


def _dedupe_candidates(candidates: list[ApplyUrlCandidate]) -> list[ApplyUrlCandidate]:
    deduped: list[ApplyUrlCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.url
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _dedupe_rejections(rejected: list[RejectedApplyCandidate]) -> list[RejectedApplyCandidate]:
    deduped: list[RejectedApplyCandidate] = []
    seen: set[tuple[str, str]] = set()
    for rejection in rejected:
        key = (rejection.url, rejection.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rejection)
    return deduped


def _is_social_share_url(lowered_url: str) -> bool:
    social_domains = ("facebook.com", "twitter.com", "x.com", "linkedin.com", "xing.com")
    if not any(domain in lowered_url for domain in social_domains):
        return False
    return any(token in lowered_url for token in ("share", "sharing", "intent", "social"))


def _identity_tokens(value: str) -> set[str]:
    parsed = urlsplit(value)
    raw_values = [parsed.path, parsed.query]
    for _key, item in parse_qsl(parsed.query, keep_blank_values=True):
        raw_values.append(item)
    tokens = set(re.findall(r"[A-Za-z0-9_-]{5,}", " ".join(raw_values)))
    return {token.lower() for token in tokens if any(char.isdigit() for char in token)}


def _has_job_parameter(value: str) -> bool:
    parsed = urlsplit(value)
    return any(JOB_PARAM_PATTERN.search(key) and item for key, item in parse_qsl(parsed.query))


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[TRUNCATED]"
