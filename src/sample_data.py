from __future__ import annotations

from pathlib import Path

from src.schemas import CandidateProfile, ExperienceUnit, JobListing, TrackerRecord
from src.storage import ensure_data_dirs, save_model


def get_sample_candidate_profile() -> CandidateProfile:
    return CandidateProfile(
        id="candidate-001",
        full_name="Alex Mercer",
        professional_summary=(
            "Python-focused operations and automation specialist with experience "
            "building internal tools, streamlining manual workflows, and translating "
            "business requirements into reliable data products."
        ),
        target_roles=["Python Developer", "Automation Engineer", "Data Analyst"],
        target_locations=["Berlin", "Remote", "Madrid"],
        skills=["Python", "SQL", "Streamlit", "APIs", "Automation", "Git", "Pandas"],
        languages=["English", "Spanish"],
        salary_expectation="EUR 55,000 - 65,000",
        constraints=["Prefer hybrid or remote-friendly roles", "No visa sponsorship needed"],
        documents_used=["CV_2026.pdf", "portfolio.md"],
    )


def get_sample_experience_units() -> list[ExperienceUnit]:
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
    return JobListing(
        id="job-001",
        title="Python Automation Specialist",
        company="Example Systems",
        source_url="https://example.com/jobs/python-automation-specialist",
        retrieval_mode="url",
        source_job_id="example-python-automation-specialist",
        location="Berlin",
        remote_policy="Hybrid",
        apply_url="https://example.com/jobs/python-automation-specialist",
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
    return [
        TrackerRecord(
            job_id="job-001",
            title="Python Automation Specialist",
            company="Example Systems",
            source_url="https://example.com/jobs/python-automation-specialist",
            location="Berlin",
            retrieval_mode="url",
            match_score=82.0,
            status="interesting",
            notes="Strong overlap with automation and reporting experience.",
        ),
        TrackerRecord(
            job_id="job-002",
            title="Data Analyst",
            company="Harbor Metrics",
            source_url="https://example.com/jobs/data-analyst",
            location="Remote",
            retrieval_mode="url",
            match_score=74.0,
            status="analyzed",
            notes="Good fit on analytics, weaker on experimentation tooling.",
        ),
        TrackerRecord(
            job_id="job-003",
            title="Operations Coordinator",
            company="City Freight",
            source_url="https://example.com/jobs/operations-coordinator",
            location="Madrid",
            retrieval_mode="url",
            match_score=None,
            status="new",
            notes="Saved for later review.",
        ),
    ]


def bootstrap_sample_data(base_dir: Path | str = ".") -> None:
    root = Path(base_dir)
    ensure_data_dirs(root)

    files_to_seed = {
        root / "data/profile.json": get_sample_candidate_profile(),
        root / "data/experience_units.json": get_sample_experience_units(),
        root / "data/tracker.json": get_sample_tracker_records(),
    }

    for path, payload in files_to_seed.items():
        if not path.exists():
            save_model(path, payload)
