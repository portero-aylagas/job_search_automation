from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.app_workflow import get_application_package_blockers
from src.application_package import apply_application_package_quality_checks
from src.application_requirements import (
    discover_application_requirements,
    inspect_application_page_agent,
    normalize_application_requirements,
)
from src.apply_url_resolution import (
    choose_apply_url_deterministically,
    run_apply_url_resolution_graph,
)
from src.cv_extraction import (
    LLMCandidateCVExtractedResponse,
    LLMCandidateCVIdentityResponse,
    normalize_cv_extracted,
)
from src.job_intake import create_job_listing, validate_apply_url
from src.llm_job_extraction import (
    DynamicJobDetail,
    LLMExtractedJobDataResponse,
    normalize_extracted_job_data,
)
from src.schemas import (
    ApplicationArtifact,
    ApplicationFormField,
    ApplicationPackage,
    ApplicationPageSnapshot,
    ApplicationRequirementFinding,
    ApplicationRequirements,
    ApplicationScreeningQuestion,
    CandidateProfile,
    JobListing,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_job(
    *,
    title: str = "Automation Engineer",
    company: str = "Example Co",
    source_url: str = "https://example.com/jobs/automation-engineer-12345",
    apply_url: str = "https://ats.example.com/apply/automation-engineer?job_id=12345",
    source_job_id: str = "12345",
    description: str = "Build Python automation and improve operational workflows.",
    requirements: list[str] | None = None,
) -> JobListing:
    return create_job_listing(
        title=title,
        company=company,
        source_url=source_url,
        apply_url=apply_url,
        source_job_id=source_job_id,
        description=description,
        requirements=requirements or ["Python", "Workflow automation"],
        now=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


def complete_candidate_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_profile={
            "profile_status": "draft",
            "source_documents": {
                "cv": {
                    "file_path": "data/runtime/candidate_profile/cv/erika-cv.pdf",
                    "parsed": True,
                },
                "optional_documents": [],
            },
            "cv_extracted": {
                "identity": {
                    "full_name": "Erika Musterfrau",
                    "first_name": "Erika",
                    "last_name": "Musterfrau",
                    "gender": "Female",
                    "email": "erika@example.com",
                    "phone": "+491701234567",
                    "street_address": "Musterstrasse",
                    "street_number": "12",
                    "postal_code": "10115",
                    "city": "Berlin",
                    "country": "Germany",
                    "nationality": "German",
                },
                "work_experience": [
                    "Built Python workflow automation for operations teams.",
                    "Maintained SQL dashboards for weekly reporting.",
                ],
                "education": ["BSc Business Informatics"],
                "skills": ["Python", "SQL", "Workflow automation"],
                "languages": ["German", "English"],
                "certifications": [],
                "projects": ["Job application workflow assistant"],
                "references": [],
            },
            "candidate_preferences": {},
        }
    )


def discovered_requirements(job: JobListing, *, reviewed: bool = False) -> ApplicationRequirements:
    return ApplicationRequirements(
        job_id=job.id,
        apply_url=job.apply_url,
        source_url=job.source_url,
        status="discovered",
        review_status="reviewed" if reviewed else "draft",
        job_preserving=True,
        required_documents=[
            ApplicationRequirementFinding(
                label="CV or resume",
                required=True,
                evidence="Upload CV",
                confidence="high",
                constraints=[".pdf"],
            )
        ],
        confidence="high",
    )


def test_cv_fixture_normalizes_identity_and_lists() -> None:
    payload = LLMCandidateCVExtractedResponse(
        identity=LLMCandidateCVIdentityResponse(
            full_name="  Erika Musterfrau  ",
            salutation=" Frau ",
            email=" ERIKA.MUSTERFRAU@EXAMPLE.COM ",
            phone=" 0049 (170) 123-4567 ",
        ),
        skills=["- Python\n- SQL", "python", " 1. Workflow automation "],
        languages=[" German\n English ", "german"],
        work_experience=["- Automation Analyst\n\n- BI Intern", "Automation Analyst"],
    )

    extracted = normalize_cv_extracted(payload)

    assert extracted.identity.full_name == "Erika Musterfrau"
    assert extracted.identity.first_name == "Erika"
    assert extracted.identity.last_name == "Musterfrau"
    assert extracted.identity.gender == "Female"
    assert extracted.identity.email == "erika.musterfrau@example.com"
    assert extracted.identity.phone == "+491701234567"
    assert extracted.skills == ["Python", "SQL", "Workflow automation"]
    assert extracted.languages == ["German", "English"]
    assert extracted.work_experience == ["Automation Analyst", "BI Intern"]


def test_job_extraction_fixture_normalizes_provider_output_and_valid_apply_url() -> None:
    payload = LLMExtractedJobDataResponse(
        title=" Automation Engineer ",
        company=" Example Co ",
        apply_url=" https://ats.example.com/apply/automation-engineer?job_id=max-4711 ",
        requirements=["Python", "python", " SQL ", ""],
        dynamic_fields=[
            DynamicJobDetail(
                name="Travel",
                value="10%",
                category="working_conditions",
                source_text="Travel: 10%",
                confidence="medium",
            )
        ],
        source_job_id=" max-4711 ",
    )

    extracted = normalize_extracted_job_data(payload)

    assert extracted.title == "Automation Engineer"
    assert extracted.company == "Example Co"
    assert extracted.apply_url == "https://ats.example.com/apply/automation-engineer?job_id=max-4711"
    assert extracted.requirements == ["Python", "SQL"]
    assert extracted.dynamic_fields[0].model_dump(mode="json") == {
        "name": "Travel",
        "value": "10%",
        "category": "working_conditions",
        "source_text": "Travel: 10%",
        "confidence": "medium",
    }
    validate_apply_url(
        extracted.apply_url,
        "https://example.com/jobs/automation-engineer-max-4711",
    )


def test_apply_url_fixture_resolves_only_job_preserving_ats_target() -> None:
    source_url = "https://example.com/jobs/automation-engineer-max-4711"
    html = """
    <html><body>
      <a href="mailto:jobs@example.com">Apply by email</a>
      <a href="/talent-community">Apply through our talent community</a>
      <a href="/jobs">Career portal application</a>
      <a href="/apply/automation-engineer?job_id=max-4711">Apply now</a>
    </body></html>
    """

    def fake_fetcher(url: str):
        if "job_id=max-4711" in url:
            return {
                "requested_url": url,
                "final_url": "https://ats.example.com/apply/automation-engineer?job_id=max-4711",
                "html": "<h1>Automation Engineer</h1><p>Example Co application form.</p>",
                "status_code": 200,
                "content_type": "text/html",
                "errors": [],
            }
        return {
            "requested_url": url,
            "final_url": url,
            "html": "<h1>Careers</h1><p>Search jobs and join our talent community.</p>",
            "status_code": 200,
            "content_type": "text/html",
            "errors": [],
        }

    state = run_apply_url_resolution_graph(
        source_url,
        title="Automation Engineer",
        company="Example Co",
        source_job_id="max-4711",
        page_content=html,
        fetcher=fake_fetcher,
        ranker=choose_apply_url_deterministically,
    )

    assert state["candidate_discovery_mode"] == "static_candidates_found"
    assert state["resolution"].status == "resolved"
    assert (
        state["resolution"].apply_url
        == "https://ats.example.com/apply/automation-engineer?job_id=max-4711"
    )
    assert state["verified_candidates"][0].job_preserving_signals == [
        "title: Automation Engineer",
        "company: Example Co",
        "source_job_id: max-4711",
        "job/requisition parameter in URL",
    ]
    rejection_reasons = {item.reason for item in state["rejected_candidates"]}
    assert "Candidate is an email or phone link, not an application URL." in rejection_reasons
    assert "Candidate points to a talent-community signup." in rejection_reasons
    assert "Destination appears generic or non-application related." in rejection_reasons


def test_requirements_fixture_interprets_upload_and_consent_html() -> None:
    job = make_job()
    snapshots: list[ApplicationPageSnapshot] = []

    def fake_extractor(
        received_job: JobListing,
        snapshot: ApplicationPageSnapshot,
    ) -> ApplicationRequirements:
        snapshots.append(snapshot)
        return ApplicationRequirements(
            job_id="provider-job",
            apply_url="https://provider.example/wrong",
            source_url="https://provider.example/source",
            status="discovered",
            job_preserving=True,
            required_documents=[
                ApplicationRequirementFinding(
                    label="CV",
                    required=True,
                    evidence="Resume or CV",
                    confidence="high",
                    constraints=[".pdf"],
                )
            ],
            upload_expectations=[
                ApplicationRequirementFinding(
                    label="Cover letter upload",
                    required=False,
                    evidence="Cover letter",
                    confidence="high",
                    constraints=[".pdf"],
                )
            ],
            motivation_letter=ApplicationRequirementFinding(
                label="Cover letter",
                required=True,
                evidence="Please upload a cover letter.",
                confidence="high",
            ),
            consent_requirements=[
                ApplicationRequirementFinding(
                    label="Privacy consent",
                    required=True,
                    evidence="I consent to privacy and data processing terms.",
                    confidence="high",
                )
            ],
            deadlines=[
                ApplicationRequirementFinding(
                    label="Apply by 2026-06-30",
                    evidence="Apply by 2026-06-30.",
                    confidence="medium",
                )
            ],
            contact_or_fallback=[
                ApplicationRequirementFinding(
                    label="recruiting@example.com",
                    evidence="Contact recruiting@example.com.",
                    confidence="medium",
                )
            ],
            confidence="high",
        )

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("uploads_and_consent_form.html"),
        final_url=str(job.apply_url),
        extractor=fake_extractor,
    )

    assert snapshots
    assert any(control.input_type == "file" for control in snapshots[0].controls)
    assert any("privacy" in evidence.lower() for evidence in snapshots[0].evidence_matches)
    assert requirements.job_id == job.id
    assert str(requirements.apply_url) == str(job.apply_url)
    assert str(requirements.source_url) == str(job.source_url)
    assert requirements.required_documents[0].label == "CV"
    assert requirements.upload_expectations[0].label == "Cover letter upload"
    assert requirements.motivation_letter is not None
    assert requirements.consent_requirements[0].required is True
    assert requirements.deadlines[0].label == "Apply by 2026-06-30"
    assert requirements.contact_or_fallback[0].label == "recruiting@example.com"


def test_requirements_fixture_interprets_screening_question_html() -> None:
    job = make_job()
    snapshots: list[ApplicationPageSnapshot] = []

    def fake_extractor(
        received_job: JobListing,
        snapshot: ApplicationPageSnapshot,
    ) -> ApplicationRequirements:
        snapshots.append(snapshot)
        return ApplicationRequirements(
            job_id=received_job.id,
            apply_url=received_job.apply_url,
            source_url=received_job.source_url,
            status="discovered",
            job_preserving=True,
            screening_questions=[
                ApplicationScreeningQuestion(
                    question="Are you authorized to work in Germany?",
                    required=True,
                    input_type="select",
                    evidence="Are you authorized to work in Germany?",
                    confidence="high",
                ),
                ApplicationScreeningQuestion(
                    question="What is your notice period?",
                    required=True,
                    input_type="text",
                    evidence="What is your notice period?",
                    confidence="high",
                ),
            ],
            custom_form_fields=[
                ApplicationFormField(
                    name="salary_expectation",
                    label="Salary expectation",
                    required=False,
                    input_type="text",
                    evidence="Salary expectation",
                    confidence="medium",
                )
            ],
            confidence="high",
        )

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("screening_questions_form.html"),
        extractor=fake_extractor,
    )

    assert any(
        control.name == "work_permit" and control.required for control in snapshots[0].controls
    )
    assert requirements.screening_questions[0].question == (
        "Are you authorized to work in Germany?"
    )
    assert requirements.screening_questions[0].required is True
    assert requirements.screening_questions[1].question == "What is your notice period?"
    assert requirements.screening_questions[1].required is True
    assert requirements.custom_form_fields[0].label == "Salary expectation"
    assert requirements.custom_form_fields[0].required is False


def test_generic_careers_fixture_blocks_before_extraction() -> None:
    job = make_job(
        source_url="https://example.com/jobs/automation-engineer",
        apply_url="https://example.com/careers",
    )
    snapshot = inspect_application_page_agent(
        job,
        page_content=fixture_html("generic_career_page.html"),
    )

    def fail_extractor(
        _job: JobListing,
        _snapshot: ApplicationPageSnapshot,
    ) -> ApplicationRequirements:
        raise AssertionError("Extractor should not run for generic career pages.")

    requirements = discover_application_requirements(
        job,
        page_content=fixture_html("generic_career_page.html"),
        extractor=fail_extractor,
    )

    assert snapshot.job_preserving_signals == []
    assert requirements.status == "blocked"
    assert requirements.job_preserving is False
    assert requirements.blocked_reason == (
        "Apply page is a generic careers page and does not preserve the selected job."
    )


def test_package_quality_fixture_flags_unsafe_generated_content() -> None:
    candidate_profile = complete_candidate_profile()
    job = make_job(
        title="Platform Automation Engineer",
        source_url="https://example.com/jobs/platform-automation-engineer",
        apply_url="https://ats.example.com/apply/platform-automation-engineer?job_id=999",
        source_job_id="999",
        requirements=["Kubernetes"],
    )
    package = ApplicationPackage(
        job_id=job.id,
        artifacts=[
            ApplicationArtifact(
                id="cover-letter",
                type="cover_letter",
                label="Cover Letter",
                required=True,
                content="I have experience with Kubernetes in production systems.",
            ),
            ApplicationArtifact(
                id="disability-answer",
                type="form_answer",
                label="Severe disability disclosure",
                source_prompt="Do you have a severe disability you want to disclose?",
                content="No.",
            ),
            ApplicationArtifact(
                id="referral-answer",
                type="form_answer",
                label="Referral code",
                source_prompt="Were you referred by an employee?",
                content="No referral.",
            ),
        ],
    )

    checked = apply_application_package_quality_checks(package, candidate_profile, job)

    assert checked.status == "needs_review"
    findings_by_id = {
        artifact.id: artifact.metadata["quality_findings"] for artifact in checked.artifacts
    }
    assert findings_by_id["cover-letter"] == [
        "Claims experience with unsupported requirement: Kubernetes"
    ]
    assert findings_by_id["disability-answer"] == [
        "Generated answer for a sensitive or user-decision field."
    ]
    assert findings_by_id["referral-answer"] == [
        "Generated answer for a sensitive or user-decision field."
    ]
    assert {artifact.status for artifact in checked.artifacts} == {"needs_review"}


def test_workflow_blocker_fixture_prevents_package_generation() -> None:
    candidate_profile = complete_candidate_profile()
    job = make_job()
    draft_requirements = discovered_requirements(job, reviewed=False)
    blocked_requirements = normalize_application_requirements(
        job,
        discovered_requirements(job, reviewed=True).model_copy(
            update={
                "status": "blocked",
                "job_preserving": False,
                "blocked_reason": "Apply page does not preserve the selected job identity.",
            }
        ),
    )
    reviewed_requirements = discovered_requirements(job, reviewed=True)

    assert get_application_package_blockers(candidate_profile, job, draft_requirements) == [
        "Review the application requirements before generating application material."
    ]
    assert get_application_package_blockers(candidate_profile, job, blocked_requirements) == [
        "Resolve application requirements before generating application material."
    ]
    assert get_application_package_blockers(candidate_profile, job, reviewed_requirements) == []
