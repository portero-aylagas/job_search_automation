from pathlib import Path

from src.sample_data import bootstrap_sample_data


def test_bootstrap_sample_data_creates_expected_files(tmp_path: Path) -> None:
    bootstrap_sample_data(tmp_path)

    assert (tmp_path / "data/candidate_profile.json").is_file()
    assert (tmp_path / "data/experience_units.json").is_file()
    assert (tmp_path / "data/jobs.json").is_file()
    assert (tmp_path / "data/tracker.json").is_file()
    assert (tmp_path / "data/runtime/jobs.json").is_file()
    assert (tmp_path / "data/runtime/tracker.json").is_file()
    assert (tmp_path / "data/jobs").is_dir()
    assert (tmp_path / "data/runtime/jobs/job-001/normalized_job.json").is_file()
    assert (tmp_path / "data/jobs/job-001/normalized_job.json").is_file()
    assert not (tmp_path / "data/applications").exists()
    assert (tmp_path / "outputs").is_dir()


def test_bootstrap_sample_data_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    profile_path = tmp_path / "data/candidate_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    original = "{\"id\": \"existing-profile\"}\n"
    profile_path.write_text(original, encoding="utf-8")

    bootstrap_sample_data(tmp_path)

    assert profile_path.read_text(encoding="utf-8") == original
