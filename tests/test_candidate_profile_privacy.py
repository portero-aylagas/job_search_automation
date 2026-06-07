from pathlib import Path

import pytest

from src.services.candidate_profile_service import (
    CandidateProfileServiceError,
    delete_runtime_candidate_file,
    ensure_runtime_candidate_file_exists,
)


def test_candidate_profile_outputs_are_gitignored() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert "data/runtime/" in gitignore
    assert "data/candidate_profile.json" in gitignore
    assert "outputs/*" in gitignore
    assert "!outputs/.gitkeep" in gitignore


def test_makefile_has_local_state_cleanup_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "clean-local-state:" in makefile
    assert "data/runtime" in makefile
    assert "data/candidate_profile.json" in makefile
    assert "outputs" in makefile
    assert "browser artifacts" in makefile


def test_readme_documents_private_local_cleanup_paths() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Local Cleanup And Privacy" in readme
    assert "make clean-local-state" in readme
    assert "data/runtime/" in readme
    assert "data/candidate_profile.json" in readme
    assert "outputs/" in readme
    assert "reports/" in readme
    assert "Browser Use runtime state" in readme
    assert "Normal app use does not delete this data automatically." in readme


def test_runtime_candidate_file_check_accepts_candidate_upload_path(tmp_path: Path) -> None:
    upload_path = tmp_path / "data" / "runtime" / "candidate_profile" / "cv" / "cv.txt"
    upload_path.parent.mkdir(parents=True)
    upload_path.write_text("CV", encoding="utf-8")

    ensure_runtime_candidate_file_exists(
        tmp_path,
        "data/runtime/candidate_profile/cv/cv.txt",
    )


def test_runtime_candidate_file_check_rejects_paths_outside_candidate_area(
    tmp_path: Path,
) -> None:
    outside_path = tmp_path / "data" / "runtime" / "jobs" / "secret.txt"
    outside_path.parent.mkdir(parents=True)
    outside_path.write_text("secret", encoding="utf-8")

    with pytest.raises(CandidateProfileServiceError, match="candidate_profile"):
        ensure_runtime_candidate_file_exists(tmp_path, outside_path)


def test_delete_runtime_candidate_file_rejects_traversal_path(tmp_path: Path) -> None:
    outside_path = tmp_path / "data" / "runtime" / "secret.txt"
    outside_path.parent.mkdir(parents=True)
    outside_path.write_text("secret", encoding="utf-8")

    with pytest.raises(CandidateProfileServiceError, match="candidate_profile"):
        delete_runtime_candidate_file(
            tmp_path,
            "data/runtime/candidate_profile/../secret.txt",
        )

    assert outside_path.exists()
