"""Shared candidate-profile actions used by API handlers and Karen tools."""

from __future__ import annotations

import base64
from pathlib import Path

from src.app_workflow import load_candidate_profile, save_candidate_profile
from src.candidate_profile import (
    UPLOAD_TIMESTAMP_PREFIX_PATTERN,
    is_valid_email,
    merge_supplemental_extracted_data,
    normalize_candidate_profile_documents,
    validate_candidate_profile,
)
from src.cv_extraction import (
    run_cv_extraction_task,
    run_optional_document_extraction_task,
    save_uploaded_cv,
    save_uploaded_optional_document,
)
from src.observability import set_current_trace_metadata, traceable
from src.paths import RUNTIME_DATA_DIR
from src.schemas import (
    CandidateCVExtracted,
    CandidateOptionalDocument,
    CandidateProfile,
    CandidateSourceCV,
    CandidateSupplementalExtracted,
)


class CandidateProfileServiceError(RuntimeError):
    """Raised when a candidate-profile service action cannot complete."""


def decode_uploaded_file(content_base64: str) -> bytes:
    """Decode a browser-uploaded base64 file payload."""

    try:
        return base64.b64decode(content_base64)
    except ValueError as exc:
        raise CandidateProfileServiceError(
            "Uploaded file content is not valid base64."
        ) from exc


def save_candidate_review_fields(
    base_dir: Path | str,
    profile: CandidateProfile,
) -> CandidateProfile:
    """Persist edited CV review fields as the current candidate draft."""

    normalized = normalize_candidate_profile_documents(profile)
    email = normalized.candidate_profile.cv_extracted.identity.email
    if email and not is_valid_email(email):
        raise CandidateProfileServiceError(
            "Email must be a valid address before saving CV review changes."
        )
    save_candidate_profile(base_dir, normalized)
    return normalized


def save_candidate_preferences(
    base_dir: Path | str,
    profile: CandidateProfile,
) -> CandidateProfile:
    """Persist manual candidate preference edits as the current draft."""

    normalized = normalize_candidate_profile_documents(profile)
    save_candidate_profile(base_dir, normalized)
    return normalized


def save_reviewed_candidate_profile(
    base_dir: Path | str,
    profile: CandidateProfile,
) -> CandidateProfile:
    """Validate and persist the reviewed candidate profile."""

    normalized = normalize_candidate_profile_documents(profile)
    validation_errors = validate_candidate_profile(normalized)
    if validation_errors:
        raise CandidateProfileServiceError(
            "Missing required fields: " + ", ".join(validation_errors)
        )
    save_candidate_profile(base_dir, normalized)
    return normalized


def parse_uploaded_cv(
    base_dir: Path | str,
    *,
    filename: str,
    content: bytes,
) -> CandidateProfile:
    """Save an uploaded CV and load extracted data into the review draft."""

    saved_path = save_uploaded_cv(base_dir, filename, content)
    try:
        extracted = _run_cv_extraction_traced(saved_path)
    except Exception as exc:
        raise CandidateProfileServiceError(
            f"CV upload was saved to {saved_path}, but AI parsing failed: {exc}. "
            "Check that the API process has OPENAI_API_KEY and network access, "
            "then click Parse CV with AI again."
        ) from exc

    profile = load_candidate_profile(base_dir).model_copy(deep=True)
    profile.candidate_profile.source_documents.cv.file_path = str(saved_path)
    profile.candidate_profile.source_documents.cv.parsed = True
    profile.candidate_profile.source_documents.cv.extracted_data = extracted
    profile.candidate_profile.cv_extracted = extracted
    normalized = normalize_candidate_profile_documents(profile)
    save_candidate_profile(base_dir, normalized)
    return normalized


@traceable(
    "Candidate Profile",
    tags=("workflow:candidate_profile", "job-search-automation"),
    metadata=lambda cv_path: {
        "workflow_key": "candidate_profile",
        "source": "candidate_profile",
        "uploaded_cv_filename_stem": _uploaded_cv_filename_stem(cv_path),
        "display_name": _candidate_profile_display_name(
            filename_stem=_uploaded_cv_filename_stem(cv_path),
        ),
    },
)
def _run_cv_extraction_traced(cv_path: str | Path) -> CandidateCVExtracted:
    """Run CV extraction inside a trace and update its display metadata."""

    extracted = run_cv_extraction_task(cv_path)
    set_current_trace_metadata(
        {
            "display_name": _candidate_profile_display_name(
                extracted=extracted,
                filename_stem=_uploaded_cv_filename_stem(cv_path),
            )
        }
    )
    return extracted


def parse_uploaded_optional_document(
    base_dir: Path | str,
    *,
    filename: str,
    document_type: str,
    content: bytes,
) -> CandidateProfile:
    """Save and parse one optional supporting document."""

    saved_path = save_uploaded_optional_document(base_dir, filename, content)
    profile = load_candidate_profile(base_dir).model_copy(deep=True)
    document = CandidateOptionalDocument(
        file_path=str(saved_path),
        file_name=filename,
        document_type=document_type,
        parsed=False,
    )
    try:
        extracted = run_optional_document_extraction_task(saved_path)
    except Exception as exc:
        profile.candidate_profile.source_documents.optional_documents.append(document)
        save_candidate_profile(base_dir, normalize_candidate_profile_documents(profile))
        raise CandidateProfileServiceError(f"{filename}: {exc}") from exc

    merge_supplemental_extracted_data(profile.candidate_profile.cv_extracted, extracted)
    document.parsed = True
    document.extracted_data = extracted
    profile.candidate_profile.source_documents.optional_documents.append(document)
    normalized = normalize_candidate_profile_documents(profile)
    save_candidate_profile(base_dir, normalized)
    return normalized


def delete_candidate_document(
    base_dir: Path | str,
    *,
    file_path: str,
    document_type: str,
) -> CandidateProfile:
    """Delete one uploaded candidate document and rebuild review data."""

    profile = load_candidate_profile(base_dir).model_copy(deep=True)
    normalized_document_type = document_type.strip().casefold()
    target_path = file_path.strip()
    if normalized_document_type == "cv":
        if profile.candidate_profile.source_documents.cv.file_path.strip() != target_path:
            raise CandidateProfileServiceError("Candidate CV not found.")
        delete_runtime_candidate_file(base_dir, target_path)
        profile.candidate_profile.source_documents.cv.file_path = ""
        profile.candidate_profile.source_documents.cv.parsed = False
        profile.candidate_profile.source_documents.cv.extracted_data = None
    else:
        kept_documents: list[CandidateOptionalDocument] = []
        deleted = False
        for document in profile.candidate_profile.source_documents.optional_documents:
            if document.file_path.strip() == target_path:
                delete_runtime_candidate_file(base_dir, target_path)
                deleted = True
                continue
            kept_documents.append(document)
        if not deleted:
            raise CandidateProfileServiceError("Candidate document not found.")
        profile.candidate_profile.source_documents.optional_documents = kept_documents

    profile.candidate_profile.cv_extracted = rebuild_candidate_cv_extracted(
        base_dir,
        profile,
    )
    normalized = normalize_candidate_profile_documents(profile)
    save_candidate_profile(base_dir, normalized)
    return normalized


def delete_runtime_candidate_file(base_dir: Path | str, file_path: str) -> None:
    """Delete one runtime candidate upload inside the candidate area."""

    candidate_path = file_path.strip()
    if not candidate_path:
        return

    resolved = _resolve_runtime_candidate_file_path(base_dir, candidate_path)
    resolved.unlink(missing_ok=True)


def _resolve_runtime_candidate_file_path(base_dir: Path | str, file_path: str) -> Path:
    """Resolve a candidate upload path and enforce the runtime candidate boundary."""

    root = Path(base_dir).resolve()
    path = Path(file_path)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    allowed_root = (root / RUNTIME_DATA_DIR / "candidate_profile").resolve()
    if not resolved.is_relative_to(allowed_root):
        raise CandidateProfileServiceError(
            "Candidate upload path must stay inside data/runtime/candidate_profile."
        )
    return resolved


def rebuild_candidate_cv_extracted(
    base_dir: Path | str,
    profile: CandidateProfile,
) -> CandidateCVExtracted:
    """Rebuild merged review data from remaining uploaded documents."""

    source_documents = profile.candidate_profile.source_documents
    cv_extracted = load_or_extract_cv_data(base_dir, source_documents.cv)
    for document in source_documents.optional_documents:
        supplemental = load_or_extract_optional_document_data(base_dir, document)
        if supplemental is None:
            continue
        merge_supplemental_extracted_data(cv_extracted, supplemental)
        document.parsed = True
        document.extracted_data = supplemental
    return cv_extracted


def load_or_extract_cv_data(
    base_dir: Path | str,
    source_cv: CandidateSourceCV,
) -> CandidateCVExtracted:
    """Return stored CV extraction data or recompute it from the upload."""

    if source_cv.extracted_data is not None:
        source_cv.parsed = True
        return source_cv.extracted_data.model_copy(deep=True)
    file_path = source_cv.file_path.strip()
    if not file_path:
        return CandidateCVExtracted()
    ensure_runtime_candidate_file_exists(base_dir, file_path)
    extracted = _run_cv_extraction_traced(file_path)
    source_cv.parsed = True
    source_cv.extracted_data = extracted
    return extracted.model_copy(deep=True)


def _candidate_profile_display_name(
    *,
    extracted: CandidateCVExtracted | None = None,
    filename_stem: str = "",
) -> str:
    """Return the candidate-profile trace display name."""

    identity = extracted.identity if extracted is not None else None
    full_name = identity.full_name.strip() if identity is not None else ""
    if full_name:
        return f"Candidate Profile: {full_name}"
    split_name = (
        " ".join(
            item
            for item in (
                identity.first_name.strip() if identity is not None else "",
                identity.last_name.strip() if identity is not None else "",
            )
            if item
        )
        if identity is not None
        else ""
    )
    if split_name:
        return f"Candidate Profile: {split_name}"
    if filename_stem.strip():
        return f"Candidate Profile: {filename_stem.strip()}"
    return "Candidate Profile"


def _uploaded_cv_filename_stem(cv_path: str | Path) -> str:
    """Return a readable CV filename stem without runtime timestamp prefixes."""

    stem = Path(cv_path).stem.strip()
    return UPLOAD_TIMESTAMP_PREFIX_PATTERN.sub("", stem).strip()


def load_or_extract_optional_document_data(
    base_dir: Path | str,
    document: CandidateOptionalDocument,
) -> CandidateSupplementalExtracted | None:
    """Return stored supplemental extraction data or recompute it from the file."""

    if document.extracted_data is not None:
        document.parsed = True
        return document.extracted_data.model_copy(deep=True)
    file_path = document.file_path.strip()
    if not file_path:
        return None
    ensure_runtime_candidate_file_exists(base_dir, file_path)
    extracted = run_optional_document_extraction_task(file_path)
    document.parsed = True
    document.extracted_data = extracted
    return extracted


def ensure_runtime_candidate_file_exists(base_dir: Path | str, file_path: str) -> None:
    """Raise a clear error when a referenced candidate upload is missing."""

    resolved = _resolve_runtime_candidate_file_path(base_dir, file_path)
    if not resolved.exists():
        raise CandidateProfileServiceError(
            f"Uploaded file is missing: {resolved}. Re-upload the remaining candidate "
            "documents before deleting this item."
        )
