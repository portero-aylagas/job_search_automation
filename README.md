# Job Search Automation

Job Search Automation is a Python application for a controlled human-in-the-loop job application workflow.

The core feature is:

```text
candidate profile + job position -> validated application package
```

The application helps transform candidate data and a specific job position into structured application material such as cover letters, CV tailoring notes, recruiter messages, form answers, and application summaries.

The system is designed to keep the user in control. AI can assist with extraction, analysis, generation, job discovery, and application preparation, but the user validates the important steps.

---

## Main Workflow

```text
candidate profile
    +
job URL
    ↓
LLM-assisted extraction and human review
    ↓
normalized job listing
    ↓
application requirements discovery when apply_url is available
    ↓
candidate/job match analysis
    ↓
application package generation
    ↓
human review and approval
    ↓
application tracking
```

---

## Core Features

- candidate profile management
- reusable experience units
- URL-only job intake with LLM-assisted extraction and manual review
- job normalization
- per-job workspace for saved intake data
- candidate/job match analysis
- tailored application package generation
- editable AI-generated material
- approval and revision workflow
- application tracker
- JSON-based local storage

---

## Optional Extensions

The application can later support:

- public web job search
- import of structured job data from external tools
- job proposal and ranking
- assisted application page opening
- form-answer suggestions

These are optional input or assistance layers. The core workflow is independent of any single job board or automation provider.

---

## Out of Scope

The application does not aim to implement:

- autonomous final job submission
- LinkedIn scraping
- login/session automation
- recruiter messaging automation
- email sending
- learning from outcomes
- vector database
- full RAG system
- Notion sync

---

## Project Structure

```text
job_search_automation/
├── AGENTS.md
├── PROJECT_SPEC.md
├── IMPLEMENTATION_PLAN.md
├── README.md
├── requirements.txt
├── app.py
├── src/
│   ├── __init__.py
│   ├── schemas.py
│   ├── storage.py
│   ├── sample_data.py
│   ├── scoring.py
│   ├── llm.py
│   ├── workflow.py
│   └── job_search.py
├── data/
│   ├── profile.json
│   ├── experience_units.json
│   ├── jobs.json
│   ├── tracker.json
│   ├── runtime/
│   │   ├── jobs.json
│   │   ├── tracker.json
│   │   └── jobs/
│   │       └── <job_id>/
│   │           ├── normalized_job.json
│   │           ├── analysis.json
│   │           ├── application_requirements.json
│   │           └── application_package.json
│   └── jobs/
│       └── <job_id>/
│           ├── normalized_job.json
│           ├── analysis.json
│           ├── application_requirements.json
│           └── application_package.json
├── outputs/
│   └── <job_id>/
│       └── application_package.md
├── tests/
│   └── fixtures/
└── skills/
```

The `skills/` directory contains development-support skills used during implementation and project improvement. It is not part of the runtime application unless explicitly integrated.

The `data/` directory stores structured runtime state. The `outputs/` directory
stores derived human-readable exports generated from JSON. Test, mock, example,
and template-style assets belong in `tests/fixtures/`.

---

## Data Model

### Candidate Profile

Stores structured candidate information:

- summary
- target roles
- locations
- skills
- languages
- constraints
- salary expectation
- documents used

### Experience Units

Reusable pieces of professional evidence.

### Job Listing

Normalized job data:

- title
- company
- source URL
- generated internal job ID
- hidden internal retrieval mode
- optional external/source job ID
- optional role details such as location, remote policy, description, requirements, responsibilities, nice-to-have skills, salary, posted date, and apply URL
- flexible job details metadata

The visible stable job core is `title`, `company`, and `source_url`.
`retrieval_mode` is required internal workflow metadata and is not an editable
UI field. The app generates its own `id`; external job board IDs are optional
and stored separately as `source_job_id`.

`normalized_job.json` describes the job offer. Apply-page requirements are
discovered later from `apply_url` and stored separately in
`application_requirements.json`.

`data/runtime/jobs.json` is the shared job index used by both the Tracker page
and the Jobs page. The tracked `data/jobs.json` and `data/tracker.json` files
remain templates and bootstrap mirrors.

The Job Intake screen starts with only a job URL. After AI extraction, the app
shows a review form with fixed fields and any dynamic extracted details. Dynamic
details are shown as normal name/value fields in the UI and are saved in
`job_details.dynamic_fields` with metadata for later validation.

`apply_url` must be a real `http` or `https` application action URL before the
workflow can continue to application requirements discovery or package
generation. Email addresses, `mailto:` links, contact names, and phone numbers
belong in dynamic details instead.

### Application Requirements

Apply-page requirements discovered after job-offer normalization:

- required documents
- motivation letter requirement
- screening questions
- form fields
- portfolio fields
- missing information for human review

### Job Analysis

Candidate/job comparison:

- match score
- matched skills
- missing skills
- strong experience units
- weak points
- application strategy

### Application Package

Generated material:

- variable artifacts
- job-specific form answers
- missing information checklist
- selected experience units
- package status

The package JSON is the source of truth. Markdown exports are generated from the
full package when needed. When `application_requirements.json` exists, package
generation uses it to decide which artifacts and answers are needed.

### Tracker Record

Application tracking information:

- job ID
- title
- company
- source URL
- location
- retrieval mode
- match score
- status
- notes
- generated package path

### Jobs View

The sidebar includes a `Jobs` page. It lists opportunities from the tracker and
opens a per-job workspace. The current version shows saved Job Intake data from
`data/runtime/jobs/<job_id>/normalized_job.json`: status, source and apply URLs, role
summary, requirements, responsibilities, nice-to-have skills, and dynamic
extracted details.

---

## Statuses

Supported application statuses:

```text
new
analyzed
interesting
rejected_by_user
application_draft
ready_to_apply
applied_manually
applied_with_agent_assistance
interview
rejected
offer
closed
```

---

## Installation

Create and activate a Python environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Run

```bash
streamlit run app.py
```

---

## Tests

```bash
pytest
```

---

## Environment Variables

For AI generation features, create a `.env` file:

```text
OPENAI_API_KEY=...
```

The application should still support non-AI sample/demo flows without requiring
an API key during early phases.

The active LLM extraction configuration is defined in
`src/llm_job_extraction.py`. That file currently pins the extraction model and
uses the project-local web search tool for both job-offer extraction and apply
URL resolution.

---

## Current Follow-ups

- #35: validate Apply URL reachability and job-identity preservation before downstream workflow steps.
- #36: validate AI-extracted content against the source to reduce hallucinated or unsupported fields, including rejected apply-link candidates.
- #37: add duplicate management and a proper applied-jobs view.

---

## Development Plan

Development is organized in phases:

1. project scaffold
2. job intake and normalization
3. deterministic match analysis
4. application package generation
5. human review and approval
6. LangGraph workflow orchestration
7. optional web search
8. optional assisted application

See `IMPLEMENTATION_PLAN.md` for detailed implementation phases and acceptance criteria.

---

## Specification

See `PROJECT_SPEC.md` for product scope, workflow design, data entities, UI pages, and boundaries.
