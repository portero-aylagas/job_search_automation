from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx

from src.api import create_app
from src.application_fill_plan import save_application_fill_plan
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import ApplicationFillPlan, CandidateProfile


def test_pages_route_preserves_top_level_navigation(tmp_path) -> None:
    response = asyncio.run(api_request(tmp_path, "GET", "/api/pages"))

    assert response.status_code == 200
    assert response.json()["pages"] == [
        "Candidate Profile",
        "Job Intake",
        "Jobs",
        "Tracker",
        "Agent Karen",
    ]


def test_candidate_profile_save_blocks_missing_required_fields(tmp_path) -> None:
    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/candidate-profile/save",
        json={"profile": CandidateProfile().model_dump(mode="json")},
    ))

    assert response.status_code == 400
    assert "Missing required fields" in response.json()["detail"]


def test_job_intake_save_persists_reviewed_dynamic_fields(tmp_path) -> None:
    source_url = "https://example.com/jobs/automation-engineer"
    apply_url = "https://example.com/apply/automation-engineer"

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/job-intake/save",
        json={
            "source_url": source_url,
            "extracted_data": {
                "title": "Automation Engineer",
                "company": "Example Co",
                "description": "Build automation workflows.",
                "requirements": ["Python"],
                "responsibilities": ["Maintain workflows"],
                "nice_to_have_skills": ["FastAPI"],
                "confidence": "high",
                "dynamic_fields": [
                    {
                        "name": "Department",
                        "value": "Platform",
                        "category": "team",
                        "source_text": "Platform team",
                        "confidence": "medium",
                    }
                ],
            },
            "apply_resolution": {
                "status": "resolved",
                "apply_url": apply_url,
                "notes": "",
                "evidence": ["Apply link matched job title."],
                "rejected_candidates": [],
                "confidence": "high",
            },
            "title": "Automation Engineer",
            "company": "Example Co",
            "location": "Berlin",
            "remote_policy": "Hybrid",
            "apply_url": apply_url,
            "salary": "",
            "posted_date": "",
            "source_job_id": "external-123",
            "description": "Build automation workflows.",
            "requirements": "- Python",
            "responsibilities": "- Maintain workflows",
            "nice_to_have_skills": "- FastAPI",
            "dynamic_fields": [
                {
                    "dynamic": True,
                    "name": "Department",
                    "value": "Platform",
                    "category": "team",
                    "source_text": "Platform team",
                    "confidence": "medium",
                }
            ],
        },
    ))

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["title"] == "Automation Engineer"
    assert payload["job"]["retrieval_mode"] == "url"
    assert payload["job"]["job_details"]["dynamic_fields"] == [
        {
            "dynamic": True,
            "name": "Department",
            "value": "Platform",
            "category": "team",
            "source_text": "Platform team",
            "confidence": "medium",
        }
    ]


def test_package_reject_action_is_not_exposed(tmp_path) -> None:
    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/jobs/job-123/package/reject",
        json={"reason": "No"},
    ))

    assert response.status_code == 404


def test_apply_route_launches_browser_without_streamlit_startup_wait(
    monkeypatch,
    tmp_path,
) -> None:
    job = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        description="Build automation workflows.",
    )
    persist_job_listing(tmp_path, job)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="reviewed",
        ),
    )
    captured: dict[str, object] = {}

    def fake_blockers(*args: object, **kwargs: object) -> list[str]:
        return []

    def fake_launcher(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            url=str(job.apply_url),
            pid=12345,
            log_path=Path(tmp_path) / "browser-use.log",
        )

    monkeypatch.setattr("src.api.get_apply_assistance_blockers", fake_blockers)
    monkeypatch.setattr("src.api.open_apply_url_with_browser_use_fill_plan", fake_launcher)

    response = asyncio.run(api_request(tmp_path, "POST", f"/api/jobs/{job.id}/apply"))

    assert response.status_code == 200
    assert response.json()["pid"] == 12345
    assert captured["kwargs"]["startup_wait_seconds"] == 0.0


async def api_request(
    tmp_path,
    method: str,
    path: str,
    **kwargs,
) -> httpx.Response:
    app = create_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)
