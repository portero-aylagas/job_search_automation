from pathlib import Path


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
