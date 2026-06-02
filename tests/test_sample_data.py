from pathlib import Path

from src.sample_data import bootstrap_sample_data, get_sample_job_listing
from src.storage import load_json


def test_bootstrap_sample_data_creates_empty_first_run_files(tmp_path: Path) -> None:
    bootstrap_sample_data(tmp_path)

    assert (tmp_path / "data/candidate_profile.json").is_file()
    assert (tmp_path / "data/experience_units.json").is_file()
    assert (tmp_path / "data/jobs.json").is_file()
    assert (tmp_path / "data/runtime/jobs.json").is_file()
    assert (tmp_path / "data/jobs").is_dir()
    assert load_json(tmp_path / "data/experience_units.json") == []
    assert load_json(tmp_path / "data/jobs.json") == []
    assert load_json(tmp_path / "data/runtime/jobs.json") == []
    assert not (tmp_path / "data/tracker.json").exists()
    assert not (tmp_path / "data/runtime/tracker.json").exists()
    assert not (tmp_path / "data/runtime/jobs/job-001/normalized_job.json").exists()
    assert not (tmp_path / "data/jobs/job-001/normalized_job.json").exists()
    assert not (tmp_path / "data/applications").exists()
    assert (tmp_path / "outputs").is_dir()


def test_bootstrap_sample_data_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    profile_path = tmp_path / "data/candidate_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    original = "{\"id\": \"existing-profile\"}\n"
    profile_path.write_text(original, encoding="utf-8")

    bootstrap_sample_data(tmp_path)

    assert profile_path.read_text(encoding="utf-8") == original


def test_sample_job_listing_uses_distinct_apply_url() -> None:
    job = get_sample_job_listing()

    assert str(job.apply_url) != str(job.source_url)
