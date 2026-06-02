from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.api import create_app
from src.app_workflow import load_candidate_profile
from src.application_fill_plan import load_application_fill_plan, save_application_fill_plan
from src.application_package_storage import load_application_package, save_application_package
from src.application_requirements import save_application_requirements
from src.job_intake import create_job_listing, persist_job_listing
from src.schemas import (
    AgentWorkflowState,
    ApplicationArtifact,
    ApplicationFillFieldValue,
    ApplicationFillPlan,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    CandidateProfile,
    JobListing,
)
from src.storage import save_model


def test_candidate_profile_load_returns_profile_and_options(tmp_path: Path) -> None:
    response = asyncio.run(api_request(tmp_path, "GET", "/api/candidate-profile"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["candidate_profile"]["profile_status"] == "draft"
    assert payload["options"]["gender"] == ["Male", "Female", "Diverse"]
    assert ["remote", "Remote"] in payload["options"]["remote_preference"]


def test_candidate_profile_review_rejects_invalid_email(tmp_path: Path) -> None:
    profile = complete_candidate_profile()
    profile.candidate_profile.cv_extracted.identity.email = "not-an-email"

    response = asyncio.run(api_request(
        tmp_path,
        "PUT",
        "/api/candidate-profile/review-changes",
        json={"profile": profile.model_dump(mode="json")},
    ))

    assert response.status_code == 400
    assert "valid address" in response.json()["detail"]


def test_candidate_profile_parse_cv_persists_extracted_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extracted = complete_candidate_profile().candidate_profile.cv_extracted
    monkeypatch.setattr("src.api.run_cv_extraction_task", lambda path: extracted)

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/candidate-profile/parse-cv",
        json={
            "filename": "cv.txt",
            "content_base64": base64.b64encode(b"CV content").decode("ascii"),
        },
    ))

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["candidate_profile"]["source_documents"]["cv"]["parsed"] is True
    assert payload["profile"]["candidate_profile"]["cv_extracted"]["identity"]["email"] == (
        "taylor@example.com"
    )
    saved = load_candidate_profile(tmp_path)
    assert saved.candidate_profile.source_documents.cv.file_path.endswith("cv.txt")
    assert saved.candidate_profile.cv_extracted.identity.first_name == "Taylor"


def test_job_intake_save_persists_reviewed_dynamic_fields(tmp_path: Path) -> None:
    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/job-intake/save",
        json=reviewed_job_payload(),
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


def test_job_intake_save_rejects_invalid_apply_url(tmp_path: Path) -> None:
    payload = reviewed_job_payload()
    payload["apply_url"] = "mailto:jobs@example.com"

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/job-intake/save",
        json=payload,
    ))

    assert response.status_code == 400
    assert "http or https" in response.json()["detail"]


def test_requirements_discovery_uses_graph_and_persists_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = save_job(tmp_path)
    snapshot = ApplicationPageSnapshot(
        requested_url=str(job.apply_url),
        final_url=str(job.apply_url),
        page_title="Apply",
    )
    requirements = reviewed_requirements(job, review_status="draft", job_preserving=False)

    def fake_graph(received_job: JobListing) -> dict[str, object]:
        assert received_job.id == job.id
        return {"snapshot": snapshot, "requirements": requirements}

    monkeypatch.setattr("src.api.run_requirements_discovery_graph", fake_graph)

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        f"/api/jobs/{job.id}/requirements/discover",
    ))

    assert response.status_code == 200
    payload = response.json()
    assert payload["requirements"]["job_id"] == job.id
    workspace = asyncio.run(api_request(tmp_path, "GET", f"/api/jobs/{job.id}/workspace"))
    assert workspace.json()["requirements"]["required_documents"][0]["label"] == "CV"


def test_requirements_review_returns_404_when_missing(tmp_path: Path) -> None:
    job = save_job(tmp_path)

    response = asyncio.run(api_request(
        tmp_path,
        "PUT",
        f"/api/jobs/{job.id}/requirements/review",
        json=requirements_review_payload(),
    ))

    assert response.status_code == 404
    assert response.json()["detail"] == "Application requirements not found."


def test_requirements_review_saves_reviewed_edits(tmp_path: Path) -> None:
    job = save_job(tmp_path)
    save_application_requirements(tmp_path, reviewed_requirements(job, review_status="draft"))

    response = asyncio.run(api_request(
        tmp_path,
        "PUT",
        f"/api/jobs/{job.id}/requirements/review",
        json=requirements_review_payload(required_documents_text="- [required] CV\n- Portfolio"),
    ))

    assert response.status_code == 200
    payload = response.json()["requirements"]
    assert payload["review_status"] == "reviewed"
    assert payload["job_preserving"] is True
    assert [item["label"] for item in payload["required_documents"]] == ["CV", "Portfolio"]


def test_package_generation_returns_blockers_for_incomplete_prerequisites(
    tmp_path: Path,
) -> None:
    job = save_job(tmp_path)

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        f"/api/jobs/{job.id}/package/generate",
    ))

    assert response.status_code == 400
    assert "Complete all package prerequisites" in response.json()["detail"]


def test_package_generation_uses_fake_generator_for_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_complete_profile(tmp_path)
    job = save_job(tmp_path)
    save_application_requirements(tmp_path, reviewed_requirements(job))

    def fake_generator(*args: object, **kwargs: object) -> ApplicationPackage:
        return ApplicationPackage(
            job_id=job.id,
            status="needs_review",
            artifacts=[
                ApplicationArtifact(
                    id="summary",
                    type="application_summary",
                    label="Application Summary",
                    required=True,
                    content="Draft summary",
                )
            ],
        )

    monkeypatch.setattr("src.api.generate_application_package", fake_generator)

    response = asyncio.run(api_request(
        tmp_path,
        "POST",
        f"/api/jobs/{job.id}/package/generate",
    ))

    assert response.status_code == 200
    assert response.json()["package"]["artifacts"][0]["content"] == "Draft summary"
    assert load_application_package(tmp_path, job.id) is not None


def test_fill_plan_generation_and_review_enforce_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = save_job(tmp_path)
    blocked = asyncio.run(api_request(
        tmp_path,
        "POST",
        f"/api/jobs/{job.id}/fill-plan/generate",
    ))
    assert blocked.status_code == 400

    requirements = reviewed_requirements(job)
    package = ApplicationPackage(
        job_id=job.id,
        status="approved",
        artifacts=[
            ApplicationArtifact(
                id="summary",
                type="application_summary",
                label="Application Summary",
                content="Approved summary",
            )
        ],
    )
    save_application_requirements(tmp_path, requirements)
    save_application_package(tmp_path, package, job)

    def fake_fill_plan(*args: object, **kwargs: object) -> ApplicationFillPlan:
        return ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            field_values=[
                ApplicationFillFieldValue(
                    label="First name",
                    value="Taylor",
                    required=True,
                )
            ],
        )

    monkeypatch.setattr("src.api.generate_application_fill_plan", fake_fill_plan)

    generated = asyncio.run(api_request(
        tmp_path,
        "POST",
        f"/api/jobs/{job.id}/fill-plan/generate",
    ))
    assert generated.status_code == 200
    edit_key = generated.json()["fill_plan_review"]["required_rows"][0]["edit_key"]

    reviewed = asyncio.run(api_request(
        tmp_path,
        "PUT",
        f"/api/jobs/{job.id}/fill-plan/review",
        json={"edited_values": {edit_key: "Taylor Edited"}},
    ))

    assert reviewed.status_code == 200
    assert reviewed.json()["fill_plan"]["review_status"] == "reviewed"
    assert load_application_fill_plan(tmp_path, job.id).field_values[0].value == (
        "Taylor Edited"
    )


def test_apply_route_blocks_until_reviews_are_complete(tmp_path: Path) -> None:
    job = save_job(tmp_path)

    response = asyncio.run(api_request(tmp_path, "POST", f"/api/jobs/{job.id}/apply"))

    assert response.status_code == 400
    assert "Complete the required review steps" in response.json()["detail"]


def test_apply_route_launches_browser_without_api_startup_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job = save_job(tmp_path)
    save_application_fill_plan(
        tmp_path,
        ApplicationFillPlan(
            job_id=job.id,
            apply_url=str(job.apply_url),
            review_status="reviewed",
        ),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("src.api.get_apply_assistance_blockers", lambda *args, **kwargs: [])

    def fake_launcher(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            url=str(job.apply_url),
            pid=12345,
            log_path=Path(tmp_path) / "browser-use.log",
        )

    monkeypatch.setattr("src.api.open_apply_url_with_browser_use_fill_plan", fake_launcher)

    response = asyncio.run(api_request(tmp_path, "POST", f"/api/jobs/{job.id}/apply"))

    assert response.status_code == 200
    assert response.json()["pid"] == 12345
    assert captured["kwargs"]["startup_wait_seconds"] == 0.0


def test_agent_routes_return_stable_json_shapes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = SimpleNamespace(session_id="session-1", selected_job_id="job-1")
    state = AgentWorkflowState(
        session_id="session-1",
        selected_job_id="job-1",
        blockers=[],
        next_allowed_actions=["review_requirements"],
    )
    monkeypatch.setattr("src.api.build_karen_context", lambda *args, **kwargs: context)
    monkeypatch.setattr("src.api.run_agent_workflow", lambda *args, **kwargs: state)
    monkeypatch.setattr("src.api.load_agent_chat_messages", lambda *args, **kwargs: [])

    agent = asyncio.run(api_request(
        tmp_path,
        "GET",
        "/api/agent?selected_job_id=job-1&session_id=session-1",
    ))

    assert agent.status_code == 200
    assert set(agent.json()) == {"context", "state", "messages", "action_labels"}
    assert agent.json()["state"]["selected_job_id"] == "job-1"

    chat_result = SimpleNamespace(
        context=context,
        intent=None,
        tool_result=None,
    )
    monkeypatch.setattr("src.api.process_karen_chat_turn", lambda *args, **kwargs: chat_result)

    chat = asyncio.run(api_request(
        tmp_path,
        "POST",
        "/api/agent/chat",
        json={"message": "What next?", "selected_job_id": "job-1", "session_id": "session-1"},
    ))

    assert chat.status_code == 200
    assert set(chat.json()) == {"context", "intent", "tool_result"}
    assert chat.json()["context"]["session_id"] == "session-1"


async def api_request(
    tmp_path: Path,
    method: str,
    path: str,
    **kwargs: object,
) -> httpx.Response:
    app = create_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def complete_candidate_profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_profile": {
                "source_documents": {
                    "cv": {
                        "file_path": "/tmp/candidate/cv.pdf",
                        "parsed": True,
                    }
                },
                "cv_extracted": {
                    "identity": {
                        "first_name": "Taylor",
                        "last_name": "Example",
                        "gender": "Diverse",
                        "email": "taylor@example.com",
                        "phone": "+49123456789",
                        "street_address": "Main Street",
                        "street_number": "1",
                        "postal_code": "10115",
                        "city": "Berlin",
                        "country": "Germany",
                        "nationality": "German",
                    },
                    "work_experience": ["Built automation workflows."],
                    "skills": ["Python", "FastAPI"],
                    "languages": ["English", "German"],
                },
            }
        }
    )


def save_complete_profile(tmp_path: Path) -> None:
    save_model(tmp_path / "data" / "candidate_profile.json", complete_candidate_profile())


def save_job(tmp_path: Path) -> JobListing:
    job = create_job_listing(
        title="Automation Engineer",
        company="Example Co",
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/apply/automation-engineer",
        description="Build automation workflows.",
        requirements=["Python"],
    )
    persist_job_listing(tmp_path, job)
    return job


def reviewed_requirements(
    job: JobListing,
    *,
    review_status: str = "reviewed",
    job_preserving: bool = True,
) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=str(job.apply_url),
        source_url=str(job.source_url),
        review_status=review_status,
        job_preserving=job_preserving,
        required_documents=[
            ApplicationRequirementFinding(label="CV", required=True, confidence="high")
        ],
        confidence="high",
    )


def requirements_review_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "job_preserving": True,
        "confidence": "high",
        "blocked_reason": "",
        "required_documents_text": "- [required] CV",
        "upload_expectations_text": "",
        "motivation_label": "",
        "motivation_required": False,
        "profile_fields_text": "",
        "screening_questions_text": "",
        "custom_form_fields_text": "",
        "consent_requirements_text": "",
        "privacy_login_ats_gates_text": "",
        "deadlines_text": "",
        "contact_or_fallback_text": "",
        "missing_or_uncertain_text": "",
    }
    payload.update(overrides)
    return payload


def reviewed_job_payload() -> dict[str, object]:
    source_url = "https://example.com/jobs/automation-engineer"
    apply_url = "https://example.com/apply/automation-engineer"
    return {
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
    }
