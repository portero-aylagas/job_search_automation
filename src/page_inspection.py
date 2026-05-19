from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.schemas import (
    ApplicationPageControl,
    ApplicationPageFormSummary,
    JobPageLink,
)

MAX_PAGE_CHARS = 80_000
MAX_SNAPSHOT_TEXT_CHARS = 20_000
MAX_EMBEDDED_JSON_ITEMS = 20

SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(cookie|session|csrf|xsrf|token|authorization|auth|password|secret|api[_-]?key)"
    r"([\"'\s:=]+)([^\"'\s<>&]{6,})"
)


def fetch_page(url: str, *, byte_limit: int = MAX_PAGE_CHARS) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8,de;q=0.7",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True, stream=True)
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            remaining = byte_limit - total
            if remaining <= 0:
                break
            piece = chunk[:remaining]
            chunks.append(piece)
            total += len(piece)
        response.close()
        encoding = response.encoding or "utf-8"
        html = b"".join(chunks).decode(encoding, errors="replace")
        return {
            "requested_url": url,
            "final_url": response.url or url,
            "html": html,
            "fetch_status": response.status_code,
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
            "fetch_status": None,
            "content_type": "",
            "errors": [f"HTTP fetch failed: {exc.__class__.__name__}: {exc}"],
        }


def parse_page_document(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    fetch_status: int | None,
    content_type: str,
    errors: list[str] | None = None,
    browser_fallback_used: bool = False,
) -> dict[str, Any]:
    clipped_html = clip(redact(html), MAX_PAGE_CHARS)
    raw_soup = BeautifulSoup(clipped_html or "", "html.parser")
    text_soup = BeautifulSoup(clipped_html or "", "html.parser")
    for element in text_soup(["script", "style", "noscript"]):
        element.extract()

    visible_text = clip(redact(text_soup.get_text(" ", strip=True)), MAX_SNAPSHOT_TEXT_CHARS)
    title = raw_soup.title.get_text(" ", strip=True) if raw_soup.title else ""
    snapshot_errors = list(errors or [])
    if not clipped_html:
        snapshot_errors.append("No static HTML content was available for inspection.")

    return {
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "fetch_status": fetch_status,
        "content_type": content_type,
        "page_title": clip(redact(title), 500),
        "visible_text_excerpt": visible_text,
        "headings": parse_headings(raw_soup),
        "links": parse_links(raw_soup, final_url or requested_url),
        "buttons": parse_buttons(raw_soup, final_url or requested_url),
        "forms": parse_forms(raw_soup),
        "controls": parse_controls(raw_soup),
        "embedded_json_summaries": parse_embedded_json(raw_soup),
        "raw_html_excerpt": clip(clipped_html, MAX_SNAPSHOT_TEXT_CHARS),
        "errors": snapshot_errors,
        "browser_fallback_used": browser_fallback_used,
    }


def page_needs_browser_fallback(
    *,
    raw_html_excerpt: str,
    visible_text_excerpt: str,
    fetch_status: int | None,
    has_interactive_elements: bool,
) -> bool:
    if not raw_html_excerpt.strip():
        return True
    if fetch_status in {401, 403, 429, 500, 502, 503}:
        return True
    text = visible_text_excerpt.lower()
    js_shell_signals = ("enable javascript", "root", "app", "loading")
    return (
        len(text) < 200
        and not has_interactive_elements
        and any(signal in text for signal in js_shell_signals)
    )


def parse_headings(soup: BeautifulSoup) -> list[str]:
    headings = []
    for heading in soup.find_all(["h1", "h2", "h3"])[:80]:
        text = clip(redact(heading.get_text(" ", strip=True)), 300)
        if text:
            headings.append(text)
    return list(dict.fromkeys(headings))


def parse_links(soup: BeautifulSoup, base_url: str) -> list[JobPageLink]:
    links: list[JobPageLink] = []
    for element in soup.find_all("a")[:250]:
        href = str(element.get("href") or "").strip()
        text = clip(redact(element.get_text(" ", strip=True)), 300)
        attrs = data_attributes(element)
        if href:
            url = urljoin(base_url, href)
        else:
            url = ""
        if url or text or attrs:
            links.append(JobPageLink(url=url, text=text, role="link", attributes=attrs))
    return links


def parse_buttons(soup: BeautifulSoup, base_url: str) -> list[JobPageLink]:
    buttons: list[JobPageLink] = []
    selectors = ["button", "input[type=button]", "input[type=submit]", "[role=button]"]
    for element in soup.select(",".join(selectors))[:150]:
        text = (
            element.get_text(" ", strip=True)
            or element.get("value", "")
            or element.get("aria-label", "")
            or element.get("data-testid", "")
            or element.get("data-test", "")
        )
        url = element.get("href") or element.get("formaction") or element.get("data-url") or ""
        buttons.append(
            JobPageLink(
                url=urljoin(base_url, str(url)) if url else "",
                text=clip(redact(str(text)), 300),
                role="button",
                attributes=data_attributes(element),
            )
        )
    return buttons


def parse_forms(soup: BeautifulSoup) -> list[ApplicationPageFormSummary]:
    forms: list[ApplicationPageFormSummary] = []
    for form in soup.find_all("form")[:20]:
        form_soup = BeautifulSoup(str(form), "html.parser")
        labels = [
            clip(redact(label.get_text(" ", strip=True)), 300)
            for label in form.find_all("label")
        ]
        buttons = [
            clip(redact(button.get_text(" ", strip=True) or button.get("value", "")), 200)
            for button in form.find_all(["button", "input"])
            if button.name == "button" or button.get("type") in {"button", "submit"}
        ]
        forms.append(
            ApplicationPageFormSummary(
                action=redact(form.get("action", "")),
                method=(form.get("method", "get") or "get").lower(),
                labels=[label for label in labels if label],
                buttons=[button for button in buttons if button],
                controls=parse_controls(form_soup),
            )
        )
    return forms


def parse_controls(soup: BeautifulSoup) -> list[ApplicationPageControl]:
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
        label = control_label(element, soup)
        attrs = {
            key: clip(redact(" ".join(value) if isinstance(value, list) else str(value)), 300)
            for key, value in element.attrs.items()
            if key.startswith("data-")
            or key in {"accept", "aria-label", "placeholder", "name", "id"}
        }
        options = [
            clip(redact(option.get_text(" ", strip=True)), 200)
            for option in element.find_all("option")
        ]
        evidence = label or element.get("placeholder", "") or element.get("aria-label", "")
        controls.append(
            ApplicationPageControl(
                kind=kind,
                name=redact(element.get("name", "")),
                label=clip(redact(label), 300),
                input_type=redact(input_type or element.get("role", "")),
                required=element.has_attr("required") or element.get("aria-required") == "true",
                options=[option for option in options if option],
                attributes=attrs,
                evidence=clip(redact(evidence), 500),
            )
        )
    return controls


def control_label(element: Any, soup: BeautifulSoup) -> str:
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


def parse_embedded_json(soup: BeautifulSoup) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for script in soup.find_all("script")[:80]:
        script_type = (script.get("type") or "").lower()
        text = script.string or script.get_text("", strip=False)
        if not text.strip():
            continue
        if "json" in script_type:
            parsed = safe_json_loads(text)
            if parsed is not None:
                summaries.append(summarize_json(parsed, script.get("id", "")))
        else:
            for match in re.finditer(
                r"({[^{}]*(?:upload|attachment|required|file|job|apply)[^{}]*})",
                text,
                re.I,
            ):
                parsed = safe_json_loads(match.group(1))
                if parsed is not None:
                    summaries.append(summarize_json(parsed, script.get("id", "")))
        if len(summaries) >= MAX_EMBEDDED_JSON_ITEMS:
            break
    return summaries[:MAX_EMBEDDED_JSON_ITEMS]


def safe_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def summarize_json(value: Any, source_id: str = "") -> dict[str, Any]:
    text = clip(redact(json.dumps(value, ensure_ascii=True, sort_keys=True)), 1200)
    keys: list[str] = []
    if isinstance(value, dict):
        keys = [str(key) for key in list(value.keys())[:30]]
    return {"source_id": redact(source_id), "keys": keys, "summary": text}


def data_attributes(element: Any) -> dict[str, str]:
    return {
        key: clip(redact(" ".join(value) if isinstance(value, list) else str(value)), 300)
        for key, value in element.attrs.items()
        if key.startswith("data-") or key in {"aria-label", "id", "name", "class"}
    }


def redact(value: str) -> str:
    redacted = value
    redacted = re.sub(
        r"(?i)(name=[\"'][^\"']*(?:csrf|xsrf|token|session|secret|password)[^\"']*[\"']"
        r"[^>]*value=[\"'])([^\"']+)([\"'])",
        r"\1[REDACTED]\3",
        redacted,
    )
    redacted = SECRET_VALUE_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)(value=[\"'])([^\"']+)([\"'][^>]*name=[\"']"
        r"[^\"']*(?:csrf|xsrf|token|session|secret|password)[^\"']*[\"'])",
        r"\1[REDACTED]\3",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(set-cookie|authorization):\s*[^\n\r]+",
        r"\1: [REDACTED]",
        redacted,
    )
    return redacted


def clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[TRUNCATED]"
