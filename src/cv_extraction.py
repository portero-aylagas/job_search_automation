from __future__ import annotations

import mimetypes
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel

from src import llm_client
from src.paths import cv_upload_path, optional_document_upload_path
from src.schemas import CandidateCVExtracted, CandidateSupplementalExtracted


class CVDocumentSnapshot(BaseModel):
    file_path: str
    file_name: str
    file_id: str
    mime_type: str = ""


CVDocumentInspector = Callable[[Path], CVDocumentSnapshot]
CVDataExtractor = Callable[[CVDocumentSnapshot], CandidateCVExtracted]
SupplementalDataExtractor = Callable[[CVDocumentSnapshot], CandidateSupplementalExtracted]


class CVExtractionState(TypedDict, total=False):
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
    path = _validate_document_path(document_path)
    snapshot = (inspector or inspect_cv_document_agent)(path)
    return (extractor or extract_optional_document_data_with_llm)(snapshot)


def run_cv_extraction_graph(
    cv_path: str | Path,
    *,
    inspector: CVDocumentInspector | None = None,
    extractor: CVDataExtractor | None = None,
) -> CVExtractionState:
    path = _validate_cv_path(cv_path)
    state: CVExtractionState = {
        "cv_path": str(path),
        "inspector": inspector,
        "extractor": extractor,
    }
    graph = build_cv_extraction_graph()
    return graph.invoke(state)


def build_cv_extraction_graph():
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
    return llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": (
                    "You extract structured professional data from a candidate CV for a "
                    "controlled, human-in-the-loop job application workflow. The uploaded "
                    "CV document is the source of truth. Do not infer job-search "
                    "preferences, excluded roles, excluded companies, salary goals, work "
                    "authorization, or availability from the CV.\n\n"
                    "Return only information supported by the CV. Leave unknown identity "
                    "fields empty. Keep complex professional fields as simple arrays of "
                    "concise text items suitable for later human review and editing."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Extract this CV into the required candidate cv_extracted JSON "
                            "fields: identity, work_experience, education, skills, "
                            "languages, certifications, and projects."
                        ),
                    },
                    {
                        "type": "input_file",
                        "file_id": snapshot.file_id,
                    },
                ],
            },
        ],
        text_format=CandidateCVExtracted,
        operation="AI CV extraction",
    )


def extract_optional_document_data_with_llm(
    snapshot: CVDocumentSnapshot,
) -> CandidateSupplementalExtracted:
    return llm_client.parse_structured_response(
        input=[
            {
                "role": "system",
                "content": (
                    "You extract supplemental professional evidence from optional "
                    "candidate documents such as reference letters, certificates, "
                    "course records, portfolios, and other supporting materials for a "
                    "controlled, human-in-the-loop job application workflow. Return "
                    "only information directly supported by the uploaded document. Do "
                    "not infer job-search preferences, salary goals, work "
                    "authorization, or availability."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Extract supplemental candidate information into these "
                            "fields when present: work_experience, education, skills, "
                            "languages, certifications, projects, references, and "
                            "notes. Keep each item concise and suitable for human "
                            "review before saving."
                        ),
                    },
                    {
                        "type": "input_file",
                        "file_id": snapshot.file_id,
                    },
                ],
            },
        ],
        text_format=CandidateSupplementalExtracted,
        operation="AI optional document extraction",
    )


def save_uploaded_cv(base_dir: Path | str, original_name: str, file_bytes: bytes) -> Path:
    safe_name = _safe_filename(original_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = cv_upload_path(base_dir, f"{timestamp}-{safe_name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_bytes)
    return target


def save_uploaded_optional_document(
    base_dir: Path | str,
    original_name: str,
    file_bytes: bytes,
) -> Path:
    safe_name = _safe_filename(original_name, fallback="document")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = optional_document_upload_path(base_dir, f"{timestamp}-{safe_name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_bytes)
    return target


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
