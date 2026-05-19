from __future__ import annotations

import mimetypes
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel

from src.llm_job_extraction import MODEL, _get_openai_client
from src.schemas import CandidateCVExtracted

CV_UPLOAD_DIR = Path("data/runtime/candidate_profile/cv")


class CVDocumentSnapshot(BaseModel):
    file_path: str
    file_name: str
    file_id: str
    mime_type: str = ""


CVDocumentInspector = Callable[[Path], CVDocumentSnapshot]
CVDataExtractor = Callable[[CVDocumentSnapshot], CandidateCVExtracted]


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
    client = _get_openai_client()
    with path.open("rb") as file:
        uploaded_file = client.files.create(file=file, purpose="user_data")

    return CVDocumentSnapshot(
        file_path=str(path),
        file_name=path.name,
        file_id=uploaded_file.id,
        mime_type=mimetypes.guess_type(path.name)[0] or "",
    )


def extract_cv_data_with_llm(snapshot: CVDocumentSnapshot) -> CandidateCVExtracted:
    client = _get_openai_client()
    response = client.responses.parse(
        model=MODEL,
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
    )

    if response.output_parsed is None:
        raise RuntimeError("AI extraction did not return structured CV data.")
    return response.output_parsed


def save_uploaded_cv(base_dir: Path | str, original_name: str, file_bytes: bytes) -> Path:
    root = Path(base_dir)
    safe_name = _safe_filename(original_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = root / CV_UPLOAD_DIR / f"{timestamp}-{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_bytes)
    return target


def _validate_cv_path(cv_path: str | Path) -> Path:
    path = Path(cv_path)
    if not path.exists():
        raise FileNotFoundError(f"CV file not found: {path}")
    if not path.is_file():
        raise ValueError(f"CV path must point to a file: {path}")
    return path


def _safe_filename(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value
    ).strip("-")
    return normalized or "cv"
