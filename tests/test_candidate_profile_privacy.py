from pathlib import Path


def test_candidate_profile_outputs_are_gitignored() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert "data/runtime/" in gitignore
    assert "data/candidate_profile.json" in gitignore
