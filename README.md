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

## Delivered Features

- candidate profile management
- reusable experience units
- URL-only job intake with LLM-assisted extraction and manual review
- job normalization
- working apply-page requirements discovery from `apply_url` through a LangGraph
  inspection/extraction slice
- per-job workspace for saved intake data
- tailored application package generation
- editable AI-generated material
- package edit and rejection recovery workflow
- application tracker
- JSON-based local storage

## Planned Core Workflow Items

- deterministic candidate/job match analysis
- explicit package approval and ready-to-apply workflow
- tracker transitions driven by approved package state

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
│   ├── llm_client.py
│   ├── prompt_templates.py
│   ├── prompts.yaml
│   ├── cv_extraction.py
│   ├── llm_job_extraction.py
│   ├── apply_url_resolution.py
│   ├── application_requirements.py
│   ├── application_fill_plan.py
│   ├── application_package.py
│   └── ...
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
│   │           ├── application_page_snapshot.json
│   │           ├── application_requirements.json
│   │           ├── application_fill_plan.json
│   │           └── application_package.json
│   └── jobs/
│       └── <job_id>/
│           ├── normalized_job.json
│           ├── analysis.json
│           ├── application_page_snapshot.json
│           ├── application_requirements.json
│           ├── application_fill_plan.json
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

AI prompt text is stored in `src/prompts.yaml` and loaded through
`src/prompt_templates.py`. Live OpenAI calls remain behind `src/llm_client.py`,
so prompt edits and provider-boundary changes stay reviewable and separate.
LLM-facing structured response schemas for CV and job extraction live next to
their extraction modules and are normalized into the persisted application
models before anything is stored or shown in the UI.

---

## Data Model

### Candidate Profile

Stores structured candidate information:

- reviewed identity and contact fields from the CV
- required gender value: `Male`, `Female`, or `Diverse`
- normalized address fields including street number, city, postal code, country,
  and nationality when available
- target roles
- locations
- skills
- languages
- constraints
- salary expectation
- source documents used
- optional supporting documents such as references and certificates

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
discovered later from `apply_url`. The app first stores read-only page evidence
in `application_page_snapshot.json`, then stores interpreted requirements in
`application_requirements.json`. Requirements stay read-only as the discovered
page contract. The editable Browser Use execution contract is stored separately
as `application_fill_plan.json`.

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

This is implemented as the first LangGraph slice of the larger workflow:
`application page inspection -> requirements extraction`. The
`inspect_application_page_agent` node uses read-only fetch, parsing, regex
evidence, embedded JSON inspection, and optional Playwright fallback to build a
snapshot before the LLM interprets requirements. It does not submit forms,
upload files, log in, or enter personal data.

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
- cover letter drafts
- CV tailoring notes
- recruiter message drafts
- document upload checklists
- job-specific form answers
- missing information checklist
- selected experience units
- package status

The package JSON is the source of truth. Markdown exports are generated from the
full package when needed. When `application_requirements.json` exists, package
generation uses it to decide which artifacts and answers are needed.

### Application Fill Plan

`application_fill_plan.json` is generated per job after reviewed requirements
and an application package exist. It maps safe candidate data and reviewed
package `form_answer` artifacts onto discovered page fields, adds reviewed
upload files such as the saved CV, and blocks fields that require user choice or
carry privacy, consent, disability, referral, internal-employee, legal, or
ambiguous risk.

The fill-plan generator first applies deterministic mappings for stable identity
and contact fields. Remaining non-sensitive fields are sent to an AI semantic
mapper with structured candidate evidence and reviewed package form answers.
Sensitive or user-decision fields are blocked before semantic mapping.

The Jobs UI lets the user generate or refresh the draft fill plan and then
review every discovered application item in one editable form. Required page
fields must have reviewed values before the plan can be marked reviewed.
Optional fields may be intentionally reviewed as blank values. Sensitive,
consent, referral, disability, and similar fields do not bypass review: the
user must convert them into explicit reviewed values or the plan stays blocked.

Browser Use receives only the reviewed execution contract: explicit field
values, reviewed upload paths, and submit guard labels. Raw candidate profile
JSON is not passed to the browser agent.

Apply URLs that are the same as the source job page, or that are not valid
http(s) application destinations, are rejected at validation time and cannot be
saved as normalized jobs.

Package generation is gated. The candidate profile mandatory fields must be
complete, the CV must be parsed, the normalized job must include a parsed
description, and application requirements must be discovered as job-preserving
from the apply URL before a package can be generated.

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

### Browser Use Setup

The Browser Use apply-assistance flow launches a **local browser session inside
the current Python environment** from the Jobs page. In WSL, that means the
browser runtime must be available from WSL, even if you already have Chrome
installed on Windows.

Activate your project Python environment before running Browser Use setup:

```bash
cd /path/to/job_search_automation
source .venv/bin/activate
uvx --version
```

If `uvx` is available, install the Playwright Chromium runtime used by Browser
Use:

```bash
uvx playwright install chromium
```

Fallback if `uvx` is not available in your shell but Playwright is installed in
your Python environment:

```bash
python -m playwright install chromium
```

If Playwright asks for additional Linux system dependencies, run:

```bash
uvx playwright install --with-deps chromium
```

Notes:

- Run these commands from the repository root with your project Python
  environment activated.
- The current Browser Use launcher opens a local WSL browser with
  `headless=False`; it does not attach to a separate Chrome already running on
  Windows.
- On WSL, visible browser mode requires a working GUI path such as WSLg.
- If Browser Use launch fails, check the setup above first. The runtime error
  message also points back to this section.
- The Job Intake page no longer launches Browser Use. Browser automation is
  isolated to the Jobs `Apply Assistance` flow.
- Each apply-assistance run starts a fresh Browser Use process, uses an
  isolated Chromium profile, and exposes `Stop Browser Use Session` plus
  `Kill All Browser Use Processes` controls in the Jobs page.
- The current Browser Use pilot opens the reviewed apply URL and executes only
  the reviewed `application_fill_plan.json`: explicit reviewed field values,
  reviewed upload paths, and submit guard labels. Unresolved fill-plan items
  block the flow before Browser Use starts. It stops before any review or
  submission action.
- Browser Use agent runs require `OPENAI_API_KEY` in addition to the Chromium
  runtime setup described here.
---

## Run

```bash
streamlit run app.py
```

---

## Verification

```bash
make verify
```

`make verify` runs Ruff linting, including public docstring checks for
application code, Python compile checks, and the pytest suite. The command is
local and does not require live API keys.

---

## Environment Variables

For AI-assisted workflows, create a `.env` file from `.env.example`:

```text
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-5.4
```

The application should still support non-AI sample/demo flows without requiring
an API key during early phases.

Browser Use local browser launch also requires a Playwright Chromium runtime as
described in `Installation -> Browser Use Setup`.

The shared AI configuration boundary lives in `src/llm_client.py`. That module
reads `OPENAI_API_KEY`, applies the default `OPENAI_MODEL`, and owns the live
provider calls used by CV extraction, job extraction, requirements discovery,
and application-package generation.

## LLM Call Policy

All live structured LLM calls go through named profiles in `src/llm_client.py`.
The project keeps one model setting, `OPENAI_MODEL`, and varies behavior by
workflow instead of adding per-workflow model environment variables.

Evidence and decision workflows are deterministic with `temperature=0.0`: CV
extraction, optional document extraction, job URL extraction, apply URL
resolution, apply candidate ranking, and application requirements extraction.
Application package generation is the only intentionally more creative profile
with `temperature=0.6`, because it writes human-facing draft text from already
validated structured inputs.

Profiles also set explicit output-token budgets, per-request timeouts, retry
counts, disabled input truncation, and bounded web-search tool calls for the two
workflows that inspect source URLs. The OpenAI SDK client is created with
`max_retries=0`; visible project retry policy lives in `src/llm_client.py`.
Retryable failures are limited to transient rate limits, timeouts, connection
errors, and temporary provider errors. Schema, validation, configuration, bad
request, and unsupported-model failures fail immediately.

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
3. deterministic match analysis (pending)
4. application requirements discovery and package generation (implemented)
5. human review and approval
6. expand LangGraph workflow orchestration
7. optional web search
8. optional assisted application

See `IMPLEMENTATION_PLAN.md` for detailed implementation phases and acceptance criteria.

---

## Specification

See `PROJECT_SPEC.md` for product scope, workflow design, data entities, UI pages, and boundaries.
