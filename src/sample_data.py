"""Sample data factories and first-run bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from src.paths import (
    candidate_profile_path,
    experience_units_paths,
    jobs_index_paths,
)
from src.schemas import (
    CandidateProfile,
    ExperienceUnit,
    JobListing,
    TrackerRecord,
)
from src.storage import ensure_data_dirs, save_model


def get_sample_candidate_profile() -> CandidateProfile:
    """Return an empty reviewed-profile template for first-run setup."""

    return CandidateProfile(
        candidate_profile={
            "profile_status": "draft",
            "source_documents": {
                "cv": {"file_path": "", "parsed": False},
                "optional_documents": [],
            },
            "cv_extracted": {
                "identity": {
                    "full_name": "",
                    "first_name": "",
                    "last_name": "",
                    "email": "",
                    "phone": "",
                    "location": "",
                    "street_address": "",
                    "street_number": "",
                    "postal_code": "",
                    "city": "",
                    "country": "",
                    "nationality": "",
                    "linkedin_url": "",
                    "github_url": "",
                    "portfolio_url": "",
                },
                "work_experience": [],
                "education": [],
                "skills": [],
                "languages": [],
                "certifications": [],
                "projects": [],
                "references": [],
            },
            "candidate_preferences": {
                "target_roles": [],
                "target_locations": [],
                "remote_preference": [],
                "employment_type": [],
                "seniority_level": [],
                "availability": "",
                "salary_min_eur": None,
                "salary_max_eur": None,
                "work_authorization": "",
            },
        },
    )


def get_sample_experience_units() -> list[ExperienceUnit]:
    """Return example experience units used by tests and explicit demos."""

    return [
        ExperienceUnit(
            id="exp-001",
            title="Workflow Automation Analyst",
            organization="Northwind Logistics",
            date_range="2023-2026",
            summary=(
                "Built internal automation tools that reduced repetitive reporting "
                "and manual data-cleaning effort across operations teams."
            ),
            skills=["Python", "SQL", "Automation", "Stakeholder Management"],
            evidence_points=[
                "Automated weekly KPI reporting for a 20-person operations team.",
                "Replaced spreadsheet-heavy processes with Python scripts and shared templates.",
                "Documented repeatable workflows for non-technical teammates.",
            ],
        ),
        ExperienceUnit(
            id="exp-002",
            title="Business Intelligence Intern",
            organization="Blue Harbor Tech",
            date_range="2022-2023",
            summary=(
                "Supported analytics and dashboard development for recruiting and sales teams."
            ),
            skills=["SQL", "Dashboards", "Data Analysis", "Excel"],
            evidence_points=[
                "Prepared datasets for recruiter funnel reporting.",
                "Created dashboard views for weekly business reviews.",
            ],
        ),
        ExperienceUnit(
            id="exp-003",
            title="Freelance Project Builder",
            organization="Independent",
            date_range="2021-2022",
            summary=(
                "Delivered small Python and web app projects with a focus on practical tooling."
            ),
            skills=["Python", "Streamlit", "APIs", "Git"],
            evidence_points=[
                "Shipped a Streamlit dashboard for client-side reporting.",
                "Integrated third-party APIs and normalized JSON outputs for downstream use.",
            ],
        ),
    ]


def get_sample_job_listing() -> JobListing:
    """Return the example normalized job listing used by demo workspaces."""

    return JobListing(
        id="job-001",
        title="Python Automation Specialist",
        company="Example Systems",
        source_url="https://example.com/jobs/python-automation-specialist",
        retrieval_mode="url",
        source_job_id="example-python-automation-specialist",
        location="Berlin",
        remote_policy="Hybrid",
        apply_url="https://example.com/apply/python-automation-specialist",
        description=(
            "Own internal automation tools, improve operational reporting, and support "
            "cross-functional teams with lightweight applications."
        ),
        requirements=["Python", "SQL", "APIs", "Workflow automation"],
        responsibilities=[
            "Build and maintain internal productivity tools",
            "Translate manual workflows into repeatable automations",
        ],
        nice_to_have_skills=["Streamlit", "Data visualization"],
        salary="EUR 60,000",
        posted_date="2026-05-10",
        job_details={"employment_type": "Full-time"},
    )


def get_sample_tracker_records() -> list[TrackerRecord]:
    """Return the empty first-run tracker template."""

    return []


def bootstrap_sample_data(base_dir: Path | str = ".") -> None:
    """Create missing sample JSON files without overwriting local user state.

    Args:
        base_dir: Repository or test root where `data/` and `outputs/` should
            be prepared.
    """

    root = Path(base_dir)
    ensure_data_dirs(root)
    _, template_experience_units_path = experience_units_paths(root)
    (
        runtime_jobs_index_path,
        _runtime_tracker_path,
        template_jobs_index_path,
        _template_tracker_path,
    ) = jobs_index_paths(root)
    files_to_seed = {
        candidate_profile_path(root): get_sample_candidate_profile(),
        template_experience_units_path: [],
        template_jobs_index_path: get_sample_tracker_records(),
        runtime_jobs_index_path: get_sample_tracker_records(),
    }

    for path, payload in files_to_seed.items():
        if not path.exists():
            save_model(path, payload)
