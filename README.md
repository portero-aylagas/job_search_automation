# Job Search Automation

Job Search Automation is a controlled human-in-the-loop job application workflow.
The current UI is a React + TypeScript + Vite frontend backed by a FastAPI
adapter over the existing Python workflow code.

The core feature is:

```text
candidate profile + job position -> validated application package
```

The application helps transform candidate data and a specific job position into structured application material such as cover letters, CV tailoring notes, recruiter messages, form answers, and application summaries.

The system is designed to keep the user in control. AI can assist with extraction, requirements discovery, generation, future job discovery, and application preparation, but the user validates the important steps.

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
application package generation
    ↓
human review and approval
    ↓
application tracking
```

---

## Delivered Features

- React + TypeScript + Vite UI with a FastAPI adapter over the existing Python
  workflow functions
- candidate profile management
- per-document candidate upload deletion with individual `x` controls for the
  CV and each optional uploaded document
- reusable experience units
- URL-only job intake with LLM-assisted extraction and manual review
- job normalization
- working apply-page requirements discovery from `apply_url` through a LangGraph
  inspection/extraction slice
- historical deterministic candidate/job match analysis backend, disabled from
  the current known-job apply workflow
- Persistent Agent Karen side chat with persisted chat transcripts and audit
  events, using `assets/karen.png` in the panel, dashboard, and browser tab icon
- per-job workspace for saved intake data
- tailored application package generation
- editable AI-generated material
- package edit and rejection recovery workflow
- reviewed Browser Use apply assistance from the Jobs page
- application tracker
- JSON-based local storage

## Planned Core Workflow Items

- broader duplicate handling
- applied-jobs view and final manual status updates
- optional web job discovery

---

## Optional Extensions

The application can later support:

- public web job search
- import of structured job data from external tools
- job proposal and ranking
- form-answer suggestions

These are optional input or assistance layers. The core workflow is independent of any single job board or automation provider.

---

## Out of Scope

The application does not aim to implement:

- autonomous or ungranted final job submission
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
├── package.json
├── vite.config.ts
├── index.html
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── main.tsx
│       └── styles.css
├── src/
│   ├── __init__.py
│   ├── api.py
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
│   ├── job_workspace.py
│   ├── agents/
│   │   └── karen/
│   │       ├── agent_card.yaml
│   │       ├── prompts.yaml
│   │       ├── policy.py
│   │       ├── tools.py
│   │       ├── state.py
│   │       └── graph.py
│   └── ...
├── assets/
│   └── karen.png
├── data/
│   ├── profile.json
│   ├── experience_units.json
│   ├── jobs.json
│   ├── runtime/
│   │   ├── jobs.json
│   │   ├── agent_sessions/
│   │   │   └── <session_id>/
│   │   │       ├── chat.jsonl
│   │   │       ├── events.jsonl
│   │   │       └── session.json
│   │   └── jobs/
│   │       └── <job_id>/
│   │           ├── normalized_job.json
│   │           ├── analysis.json
│   │           ├── agent_chat.jsonl
│   │           ├── events.jsonl
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

The `skills/` directory contains development-support skills used during
implementation and project improvement. It is not part of the runtime
application unless explicitly integrated.

The React UI in `frontend/src/` is intentionally a workflow-parity port of the
historical Streamlit workflow, not a product redesign. It preserves the top
navigation pages:
`Candidate Profile`, `Job Intake`, `Jobs`, `Tracker`, and `Agent Karen`.
AI-triggering buttons keep the visible `with AI` labels. Structured review
forms remain structured review forms rather than raw JSON editors.

The `data/` directory stores structured runtime state. The `outputs/` directory
stores derived human-readable exports generated from JSON. Test, mock, example,
and template-style assets belong in `tests/fixtures/`.

The repository test strategy is documented in `docs/test_strategy.md`. It
defines the intended Python, FastAPI, React, and Playwright test layers, plus
the mocking boundaries for AI, Browser Use, and external network behavior.

AI prompt text is stored in `src/prompts.yaml` and loaded through
`src/prompt_templates.py`; Karen's runtime assistant prompts live with her
package in `src/agents/karen/prompts.yaml`. Live OpenAI calls remain behind
`src/llm_client.py`, so prompt edits and provider-boundary changes stay
reviewable and separate.
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
- optional target roles
- optional target locations
- skills
- languages
- constraints
- optional salary expectation
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
and the Jobs page. The tracked `data/jobs.json` file remains the bootstrap
template. Legacy `tracker.json` files are read only as migration fallback when a
canonical `jobs.json` index is missing.

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

Job analysis is not part of the current user-facing known-job apply workflow.
Existing `analysis.json` files are treated as ignored historical artifacts.
Backend code can remain for now, but Karen, normal app navigation, package
generation, and tracker progression do not require match analysis.

Future job discovery or ranking may reintroduce candidate/job comparison:

- match score
- weighted score components
- matched skills
- missing skills
- relevant evidence and strong experience units
- weak points
- recommended positioning
- application strategy

Historical analysis output used `data/runtime/jobs/<job_id>/analysis.json`.

### Karen Runtime Assistant

Karen is the runtime product assistant inside the app. Her chat appears as a
persistent app-level side panel across `Candidate Profile`, `Job Intake`,
`Jobs`, `Tracker`, and `Agent Karen`. The side panel owns the selected job,
pending-gate hint, transcript, and compact `Ask Karen` composer. The panel uses
a stable viewport-relative layout: Karen context, job selection, and pending
gate stay at the top, the transcript scrolls in the middle and auto-scrolls to
new replies, and the icon-based message composer remains at the bottom. Its
width is adjustable from the divider between the page and chat panel. The
top-level `Agent Karen` tab remains as a dashboard-only page showing
Karen's portrait from `assets/karen.png`, selected-job workflow status,
blockers, pending gate, timeline, and static next-action guidance. Karen is
separate from `AGENTS.md`, which remains development-agent guidance.

Karen transcripts are stored in
`data/runtime/agent_sessions/<session_id>/chat.jsonl`. Job-scoped copies are
stored in `data/runtime/jobs/<job_id>/agent_chat.jsonl`. Structured workflow
events are stored as `events.jsonl` in both the session directory and the
affected job directory.

Karen can explain the app and her role, inspect the current workflow state,
suggest next steps, route users to the right page, and process safe draft/local
workflow requests after explicit chat intent through the backend policy layer.
The Agent Karen dashboard displays next actions as guidance rather than direct
workflow buttons. She does not duplicate Job Intake or the detailed Jobs review
forms.

For a selected saved job with a valid `apply_url`, Karen can continue the
workflow through permissioned job-scoped actions such as requirements discovery,
draft package generation, draft fill-plan generation, apply-assistance
preparation, and Browser Use launch. She does not propose match analysis or
match review actions in the current known-job workflow.

Karen's permission model is deliberately gated:

- read-only explanation, status inspection, blockers, and routing are allowed
  directly
- local job mutations require explicit user intent and a selected-job session
  grant
- Browser Use launch requires explicit user intent plus a selected-job grant
  that enables browser launch
- final-submit mode requires explicit submit intent plus a selected-job grant
  that enables final submission
- requirements review, package approval, and fill-plan review stay in the Jobs
  page when structured reviewed fields are required

Karen never automates login, MFA, captcha handling, account creation, recruiter
messaging, review-gate bypasses, or invented candidate data from free-form chat.
Autonomous or ungranted final submission is blocked.

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

The Browser Use apply task keeps the reviewed fill-plan sections in a fixed
execution order: first fill or confirm `field_values_before_upload`, then handle
each `mandatory_checkbox_fields` item exactly once, and only then upload every
file from `upload_files_last`. Mandatory checkboxes are inspected before any
click; once a checkbox is checked or confirmed checked, the agent must not click
it again. Uploads start only after field rows and mandatory checkbox rows are
complete or explicitly reported as failed.

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

The top navigation includes a `Jobs` page. It lists opportunities from the tracker and
opens a per-job workspace. The current version shows saved Job Intake data from
`data/runtime/jobs/<job_id>/normalized_job.json`: status, source and apply URLs, role
summary, requirements, responsibilities, nice-to-have skills, and dynamic
extracted details. Karen's selected-job context remains available in the
persistent side chat and the `Agent Karen` dashboard.

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
agent_assistance_attempted
applied_manually
applied_with_agent_assistance
interview
rejected
offer
closed
```

---

## Installation

Use the repository-local Python environment when available:

```bash
PATH="$PWD/.conda/bin:$PATH"
```

If you are setting up from scratch without the repository-local environment,
create and activate a Python environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install frontend and browser-test dependencies from the repository root:

```bash
npm install
npx playwright install chromium
```

Python dependencies are tracked in `requirements.txt`. Frontend, Vitest, and
Playwright test-runner dependencies are tracked in `package.json` and
`package-lock.json`; do not add Node packages to `requirements.txt`.

If Playwright reports missing Linux system dependencies for browser tests, run
`npx playwright install --with-deps chromium`.

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
- The default Browser Use apply-assistance run opens the reviewed apply URL and
  executes only the reviewed `application_fill_plan.json`: explicit reviewed
  field values, reviewed upload paths, and submit guard labels. Unresolved
  fill-plan items block the flow before Browser Use starts. The default mode
  stops before any review or submission action.
- Karen's separate final-submit mode is available only for a selected job after
  explicit submit intent and a session grant that enables final submission.
- The Browser Use task fills reviewed fields first, processes mandatory
  checkboxes once, then uploads reviewed files last. It does not run a separate
  second checkbox verification pass before upload.
- Browser Use agent runs require `OPENAI_API_KEY` in addition to the Chromium
  runtime setup described here.

---

## Run

### React + FastAPI UI

Start the FastAPI backend in one terminal:

```bash
PATH="$PWD/.conda/bin:$PATH" uvicorn src.api:app --host 127.0.0.1 --port 8001 --reload
```

Start the Vite frontend in another terminal:

```bash
npm run frontend:dev
```

Open:

```text
http://127.0.0.1:5173/
```

During Vite development, the frontend calls `http://127.0.0.1:8001` by default.
Override this with `VITE_API_BASE_URL` if the API runs elsewhere. A fresh local
state is valid: when `data/candidate_profile.json` and `data/runtime/` are
missing, the API returns an empty draft candidate profile.

## Verification

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

`make verify` runs Ruff linting, including public docstring checks for
application code, Python compile checks, the pytest suite, frontend typecheck,
Vitest component tests, frontend production build, and Playwright browser smoke
tests. The browser smoke tests start Vite and mock backend API routes; they do
not require a live FastAPI server, live AI services, Browser Use session, or API
keys.

Verification writes local generated reports to `reports/`, `playwright-report/`,
and `test-results/`. These paths are ignored by git. In GitHub Actions, they are
uploaded as the `test-reports` artifact. On pushes to `main`, the latest
Playwright HTML report is also published to GitHub Pages and linked from the
`publish-playwright-report` job summary.

If you are using a standard virtual environment instead of the repository-local
`.conda` environment, activate it first and run `make verify` from the
repository root.

To reset local private/runtime state while keeping checked-in templates:

```bash
make clean-local-state
```

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

- #100: add one-command React/FastAPI startup and decide the production hosting
  path for the React build.
- #35: validate Apply URL reachability and job-identity preservation before downstream workflow steps.
- #36: validate AI-extracted content against the source to reduce hallucinated or unsupported fields, including rejected apply-link candidates.
- #37: add duplicate management and a proper applied-jobs view.

---

## Development Plan

Development is organized in phases:

1. project scaffold
2. job intake and normalization
3. deterministic match analysis (implemented)
4. application requirements discovery and package generation (implemented)
5. human review and approval
6. expand LangGraph workflow orchestration (implemented for the current
   human-gated workflow)
7. optional web search
8. optional assisted application

See `IMPLEMENTATION_PLAN.md` for detailed implementation phases and acceptance criteria.

---

## Specification

See `PROJECT_SPEC.md` for product scope, workflow design, data entities, UI pages, and boundaries.

### Optional LangSmith tracing

The application can send normal app LLM calls and Browser Use agent LLM calls
to LangSmith for debugging and observability. Repo-local `.env` values are
loaded automatically, but exported shell values take precedence.

Set the following environment variables:

```env
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=job-search-automation
```
