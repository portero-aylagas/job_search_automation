"""CV and supporting-document upload, inspection, and extraction workflow helpers."""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel

from src import llm_client
from src.paths import cv_upload_path, optional_document_upload_path
from src.prompt_templates import get_prompt
from src.schemas import (
    AIWorkflowTrace,
    CandidateCVExtracted,
    CandidateCVIdentity,
    CandidateSupplementalExtracted,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CV_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md"}
OPTIONAL_DOCUMENT_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")


class CVDocumentSnapshot(BaseModel):
    """Provider file reference and metadata for an uploaded document."""

    file_path: str
    file_name: str
    file_id: str
    mime_type: str = ""


class LLMCandidateCVIdentityResponse(BaseModel):
    """LLM-safe nullable identity fields extracted from a CV."""

    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None
    salutation: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    street_address: str | None = None
    street_number: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    nationality: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class LLMCandidateCVExtractedResponse(BaseModel):
    """LLM-safe nullable CV extraction response before normalization."""

    identity: LLMCandidateCVIdentityResponse | None = None
    work_experience: list[str] | None = None
    education: list[str] | None = None
    skills: list[str] | None = None
    languages: list[str] | None = None
    certifications: list[str] | None = None
    projects: list[str] | None = None
    references: list[str] | None = None


class LLMCandidateSupplementalExtractedResponse(BaseModel):
    """LLM-safe nullable extraction response for optional documents."""

    work_experience: list[str] | None = None
    education: list[str] | None = None
    skills: list[str] | None = None
    languages: list[str] | None = None
    certifications: list[str] | None = None
    projects: list[str] | None = None
    references: list[str] | None = None
    notes: list[str] | None = None


CVDocumentInspector = Callable[[Path], CVDocumentSnapshot]
CVDataExtractor = Callable[[CVDocumentSnapshot], CandidateCVExtracted]
SupplementalDataExtractor = Callable[[CVDocumentSnapshot], CandidateSupplementalExtracted]


class CVExtractionState(TypedDict, total=False):
    """State passed between CV extraction graph nodes."""

    cv_path: str
    inspector: CVDocumentInspector | None
    extractor: CVDataExtractor | None
    snapshot: CVDocumentSnapshot
    cv_extracted: CandidateCVExtracted


def run_cv_extraction_task(
    cv_path: str | Path,
    *,
    inspector: CVDocumentInspector | None = None,
    extractor: CVDataExtractor | None = None,
) -> CandidateCVExtracted:
    """Run the CV extraction graph and return normalized candidate evidence."""

    state = run_cv_extraction_graph(
        cv_path,
        inspector=inspector,
        extractor=extractor,
    )
    return state["cv_extracted"]


def run_optional_document_extraction_task(
    document_path: str | Path,
    *,
    inspector: CVDocumentInspector | None = None,
    extractor: SupplementalDataExtractor | None = None,
) -> CandidateSupplementalExtracted:
    """Inspect and extract evidence from one optional supporting document."""

    path = _validate_document_path(document_path)
    snapshot = (inspector or inspect_cv_document_agent)(path)
    return (extractor or extract_optional_document_data_with_llm)(snapshot)


def run_cv_extraction_graph(
    cv_path: str | Path,
    *,
    inspector: CVDocumentInspector | None = None,
    extractor: CVDataExtractor | None = None,
) -> CVExtractionState:
    """Run the CV extraction graph with injectable inspector and extractor steps."""

    path = _validate_cv_path(cv_path)
    state: CVExtractionState = {
        "cv_path": str(path),
        "inspector": inspector,
        "extractor": extractor,
    }
    graph = build_cv_extraction_graph()
    return graph.invoke(state)


def build_cv_extraction_graph():
    """Build the LangGraph CV extraction graph or a sequential fallback."""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _SequentialCVExtractionGraph()

    graph = StateGraph(CVExtractionState)
    graph.add_node("inspect_cv_document_agent", _inspect_cv_document_node)
    graph.add_node("extract_cv_data", _extract_cv_data_node)
    graph.set_entry_point("inspect_cv_document_agent")
    graph.add_edge("inspect_cv_document_agent", "extract_cv_data")
    graph.add_edge("extract_cv_data", END)
    return graph.compile()


class _SequentialCVExtractionGraph:
    def invoke(self, state: CVExtractionState) -> CVExtractionState:
        next_state = dict(state)
        next_state.update(_inspect_cv_document_node(next_state))
        next_state.update(_extract_cv_data_node(next_state))
        return next_state


def _inspect_cv_document_node(state: CVExtractionState) -> dict[str, CVDocumentSnapshot]:
    path = Path(state["cv_path"])
    inspector = state.get("inspector") or inspect_cv_document_agent
    return {"snapshot": inspector(path)}


def _extract_cv_data_node(state: CVExtractionState) -> dict[str, CandidateCVExtracted]:
    extractor = state.get("extractor") or extract_cv_data_with_llm
    return {"cv_extracted": extractor(state["snapshot"])}


def inspect_cv_document_agent(cv_path: Path) -> CVDocumentSnapshot:
    """Upload a validated CV file and return its provider file reference."""

    path = _validate_cv_path(cv_path)
    with path.open("rb") as file:
        uploaded_file = llm_client.upload_user_file(file)

    return CVDocumentSnapshot(
        file_path=str(path),
        file_name=path.name,
        file_id=uploaded_file.id,
        mime_type=mimetypes.guess_type(path.name)[0] or "",
    )


def extract_cv_data_with_llm(snapshot: CVDocumentSnapshot) -> CandidateCVExtracted:
    """Extract normalized candidate CV evidence using the configured LLM profile."""

    workflow_trace: AIWorkflowTrace | None = None

    def capture_trace(trace: AIWorkflowTrace) -> None:
        nonlocal workflow_trace
        workflow_trace = trace

    response = llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": get_prompt("cv_extraction", "extract_cv_data", "system"),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": get_prompt("cv_extraction", "extract_cv_data", "user_text"),
                    },
                    {
                        "type": "input_file",
                        "file_id": snapshot.file_id,
                    },
                ],
            },
        ],
        text_format=LLMCandidateCVExtractedResponse,
        operation="AI CV extraction",
        # CV extraction should stay evidence-first and repeatable.
        profile=llm_client.CV_EXTRACTION_PROFILE,
        trace_sink=capture_trace,
    )
    extracted = normalize_cv_extracted(response)
    extracted.workflow_trace = workflow_trace
    return extracted


def extract_optional_document_data_with_llm(
    snapshot: CVDocumentSnapshot,
) -> CandidateSupplementalExtracted:
    """Extract normalized supplemental evidence using the configured LLM profile."""

    workflow_trace: AIWorkflowTrace | None = None

    def capture_trace(trace: AIWorkflowTrace) -> None:
        nonlocal workflow_trace
        workflow_trace = trace

    response = llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": get_prompt(
                    "cv_extraction",
                    "extract_optional_document_data",
                    "system",
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": get_prompt(
                            "cv_extraction",
                            "extract_optional_document_data",
                            "user_text",
                        ),
                    },
                    {
                        "type": "input_file",
                        "file_id": snapshot.file_id,
                    },
                ],
            },
        ],
        text_format=LLMCandidateSupplementalExtractedResponse,
        operation="AI optional document extraction",
        # Supplemental documents are also parsed as factual evidence, not prose generation.
        profile=llm_client.OPTIONAL_DOCUMENT_EXTRACTION_PROFILE,
        trace_sink=capture_trace,
    )
    extracted = normalize_optional_document_extracted(response)
    extracted.workflow_trace = workflow_trace
    return extracted


def save_uploaded_cv(base_dir: Path | str, original_name: str, file_bytes: bytes) -> Path:
    """Validate and save an uploaded CV file under runtime candidate data."""

    safe_name = _validate_uploaded_file(
        original_name,
        file_bytes,
        allowed_extensions=CV_UPLOAD_EXTENSIONS,
        fallback="cv",
        document_label="CV",
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return _write_unique_upload_file(
        cv_upload_path(base_dir, f"{timestamp}-{safe_name}"),
        file_bytes,
    )


def save_uploaded_optional_document(
    base_dir: Path | str,
    original_name: str,
    file_bytes: bytes,
) -> Path:
    """Validate and save an uploaded optional document under runtime data."""

    safe_name = _validate_uploaded_file(
        original_name,
        file_bytes,
        allowed_extensions=OPTIONAL_DOCUMENT_UPLOAD_EXTENSIONS,
        fallback="document",
        document_label="Optional document",
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return _write_unique_upload_file(
        optional_document_upload_path(base_dir, f"{timestamp}-{safe_name}"),
        file_bytes,
    )


def _write_unique_upload_file(target: Path, file_bytes: bytes) -> Path:
    """Write upload bytes without replacing an existing same-second upload."""

    target.parent.mkdir(parents=True, exist_ok=True)
    for candidate in _unique_upload_candidates(target):
        try:
            with candidate.open("xb") as file:
                file.write(file_bytes)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not choose a unique upload filename for {target.name}.")


def _unique_upload_candidates(target: Path) -> list[Path]:
    candidates = [target]
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 1000):
        candidates.append(target.with_name(f"{stem}-{index}{suffix}"))
    return candidates


def _validate_cv_path(cv_path: str | Path) -> Path:
    return _validate_document_path(cv_path, document_label="CV")


def _validate_document_path(
    document_path: str | Path,
    *,
    document_label: str = "Document",
) -> Path:
    path = Path(document_path)
    if not path.exists():
        raise FileNotFoundError(f"{document_label} file not found: {path}")
    if not path.is_file():
        raise ValueError(f"{document_label} path must point to a file: {path}")
    return path


def _safe_filename(value: str, *, fallback: str = "cv") -> str:
    normalized = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value
    ).strip("-")
    return normalized or fallback


def _validate_uploaded_file(
    original_name: str,
    file_bytes: bytes,
    *,
    allowed_extensions: set[str],
    fallback: str,
    document_label: str,
) -> str:
    safe_name = _safe_filename(original_name, fallback=fallback)
    extension = Path(safe_name).suffix.lower()
    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"{document_label} must use one of these file types: {allowed}.")
    if not file_bytes:
        raise ValueError(f"{document_label} upload is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ValueError(f"{document_label} upload must be {max_mb} MB or smaller.")
    return safe_name


def normalize_cv_extracted(response: LLMCandidateCVExtractedResponse) -> CandidateCVExtracted:
    """Convert nullable LLM CV output into the persisted candidate model."""

    identity = response.identity or LLMCandidateCVIdentityResponse()
    return CandidateCVExtracted(
        identity=CandidateCVIdentity(
            full_name=_normalize_text(identity.full_name),
            first_name=_normalize_text(identity.first_name),
            last_name=_normalize_text(identity.last_name),
            gender=_normalize_text(identity.gender) or _normalize_text(identity.salutation),
            email=_normalize_text(identity.email),
            phone=_normalize_text(identity.phone),
            location=_normalize_text(identity.location),
            street_address=_normalize_text(identity.street_address),
            street_number=_normalize_text(identity.street_number),
            postal_code=_normalize_text(identity.postal_code),
            city=_normalize_text(identity.city),
            country=_normalize_text(identity.country),
            nationality=_normalize_text(identity.nationality),
            linkedin_url=_normalize_text(identity.linkedin_url),
            github_url=_normalize_text(identity.github_url),
            portfolio_url=_normalize_text(identity.portfolio_url),
        ),
        work_experience=_normalize_review_blocks(response.work_experience),
        education=_normalize_string_list(response.education),
        skills=_normalize_string_list(response.skills),
        languages=_normalize_string_list(response.languages),
        certifications=_normalize_string_list(response.certifications),
        projects=_normalize_string_list(response.projects),
        references=_normalize_string_list(response.references),
    )


def normalize_optional_document_extracted(
    response: LLMCandidateSupplementalExtractedResponse,
) -> CandidateSupplementalExtracted:
    """Convert nullable supplemental LLM output into the persisted model."""

    return CandidateSupplementalExtracted(
        work_experience=_normalize_review_blocks(response.work_experience),
        education=_normalize_string_list(response.education),
        skills=_normalize_string_list(response.skills),
        languages=_normalize_string_list(response.languages),
        certifications=_normalize_string_list(response.certifications),
        projects=_normalize_string_list(response.projects),
        references=_normalize_string_list(response.references),
        notes=_normalize_string_list(response.notes),
    )


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _split_reviewable_items(value):
            key = item.casefold()
            if key in seen:
                continue
            normalized.append(item)
            seen.add(key)
    return normalized


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_review_blocks(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _split_reviewable_blocks(value):
            key = item.casefold()
            if key in seen:
                continue
            normalized.append(item)
            seen.add(key)
    return normalized


def _split_reviewable_blocks(value: str) -> list[str]:
    normalized_value = value.replace("\r\n", "\n").replace("\r", "\n")
    raw_blocks = re.split(r"\n\s*\n+", normalized_value)
    blocks: list[str] = []
    for raw_block in raw_blocks:
        lines = [
            _LIST_PREFIX_RE.sub("", raw_line).strip()
            for raw_line in raw_block.splitlines()
            if raw_line.strip()
        ]
        if not lines:
            continue
        blocks.append("\n".join(lines))
    return blocks


def _split_reviewable_items(value: str) -> list[str]:
    items: list[str] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        item = _LIST_PREFIX_RE.sub("", raw_line).strip()
        if not item:
            continue
        items.append(item)
    return items
