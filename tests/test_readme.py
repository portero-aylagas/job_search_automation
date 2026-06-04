"""README policy tests."""

from pathlib import Path


def test_readme_omits_repository_local_conda_setup() -> None:
    """Ensure the public README does not advertise repo-local Conda setup."""

    readme_text = Path("README.md").read_text(encoding="utf-8").lower()

    assert "conda" not in readme_text
    assert ".conda" not in readme_text
