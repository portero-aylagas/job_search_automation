# Implementation Plan

## Development Strategy

Build the application incrementally.

The first goal is a working controlled workflow using local sample data and JSON storage.

Do not start with web search, browser automation, external APIs, or LangGraph. Those should be added after the core data model and UI are stable.

---

## Phase 1 — Project Scaffold

### Goal

Create the minimum runnable application structure.

### Create

```text
app.py
src/__init__.py
src/schemas.py
src/storage.py
src/sample_data.py
data/
outputs/
tests/
```

### Implement

- Pydantic schemas
- JSON load/save helpers
- sample candidate profile
- sample experience units
- sample job listing
- sample tracker records
- basic Streamlit app
- sidebar navigation
- Candidate Profile page
- Tracker page

### Do Not Implement Yet

- OpenAI calls
- web search
- LangGraph
- database
- browser automation

### Acceptance Criteria

- app runs with:

```bash
streamlit run app.py
```

- sample profile is visible
- sample experience units are visible
- sample tracker table is visible
- JSON helpers can save and load data
- no live API calls are required

---

## Phase 2 — Job URL Intake and Normalization

### Goal

Allow the user to add a job from a URL, review extracted details, and save a
normalized job offer.

### Implement

- Job Intake page
- first-screen Job URL input
- LLM-assisted extraction into review fields
- review UI that appears only after extraction
- manual review fallback fields:
  - title
  - company
  - source URL
- optional extracted role fields:
  - location
  - remote policy
  - apply URL
  - description
- hidden internal fields:
  - generated app job ID
  - retrieval mode
- optional external/source job ID
- dynamic extracted fields saved in `job_details.dynamic_fields`
- Apply URL validation before the workflow can continue past reviewed intake
- dedicated apply-link resolution with job-identity validation and rejected candidates
- save normalized job as JSON
- create/update tracker record with status `new`
- Jobs page that lets the user open each tracked job as its own workspace

### Data Output

```text
data/jobs/<job_id>/normalized_job.json
data/runtime/jobs.json
```

### Acceptance Criteria

- user can create one job listing from a URL
- the initial intake UI shows only the job URL and extraction action
- required visible fields are title, company, and source URL
- app generates its own internal job ID
- retrieval mode is saved as internal workflow metadata and not shown as an editable field
- external/source job ID is optional
- dynamic extracted details render as normal name/value review fields and are saved with dynamic metadata
- the workflow blocks continuation when apply_url is missing or not an http(s) URL
- the workflow blocks continuation when apply_url is not job-preserving or matches the source page
- job listing is saved as JSON
- tracker is updated
- job appears in the Tracker page
- job appears in the Jobs page with saved intake data displayed clearly

---

## Phase 3 — Deterministic Match Analysis

### Goal

Compare a job against the candidate profile using simple deterministic logic.

### Implement

- skill overlap detection
- role/title match
- location match
- constraint checks
- match score
- matched skills
- missing skills
- relevant experience units
- weak points

### Suggested Score

```text
role_match: 30%
skill_match: 35%
location_match: 20%
constraint_match: 10%
completeness/freshness: 5%
```

### Data Output

```text
data/jobs/<job_id>/analysis.json
```

### Acceptance Criteria

- user can select a job
- app calculates match analysis
- analysis is displayed
- analysis is saved
- tracker status can move to `analyzed`

---

## Phase 4 — Application Package Generation

### Goal

Generate application material from candidate profile + experience units + job
data, guided by apply-page requirements when those have been discovered.

### Implement

- application-requirements discovery from `apply_url` before or inside package generation
- validate that `apply_url` is usable before requirements discovery
- preserve job-preserving resolution evidence and rejected candidates for review
- preserve human review of discovered application requirements
- OpenAI API wrapper
- prompt templates
- manifest-driven application artifact generation
- support for variable job-specific materials
- application form answer generation
- markdown package rendering from JSON
- application package save/load

### Generated Outputs

```text
data/jobs/<job_id>/application_requirements.json
data/jobs/<job_id>/application_package.json
outputs/<job_id>/application_package.md
```

The package JSON is the source of truth. Markdown output is a derived review or
export file generated from the full package.
`normalized_job.json` describes the job offer. `application_requirements.json`
describes required documents, motivation letter needs, screening questions, and
form fields discovered later from `apply_url`.

### Acceptance Criteria

- user can select an analyzed job
- app can record application requirements when an apply URL is available
- app generates an application package
- package generation uses `application_requirements.json` when present
- generated material is visible in UI
- package is saved
- tracker status can move to `application_draft`

### Follow-up Tickets

- #35 validates `apply_url` reachability and job-identity preservation before downstream workflow continues.
- #36 adds source-grounding checks for AI-extracted content and rejected apply-link candidates to reduce hallucinated or unsupported fields.
- #37 adds duplicate handling and a proper applied-jobs view.

---

## Phase 5 — Human Review and Approval

### Goal

Add approval gates and feedback loops.

### Implement

- editable text areas for generated material
- approve button
- reject button
- regenerate with feedback
- save manual edits
- package status updates
- tracker status updates

### Supported Package Statuses

```text
draft
needs_review
approved
rejected
regenerated
manually_edited
```

### Acceptance Criteria

- user can edit generated material
- user can approve final package
- user can reject package
- user can regenerate with feedback
- tracker can move to `ready_to_apply`

---

## Phase 6 — LangGraph Workflow Orchestration

### Goal

Move the workflow into a clear state machine.

### Implement

- `WorkflowState`
- LangGraph nodes:
  - load_candidate_profile
  - receive_job_input
  - normalize_job
  - human_validate_job
  - analyze_match
  - human_validate_analysis
  - generate_application_package
  - human_review_application
  - revise_application_package
  - save_application_package
  - update_tracker
- conditional branches:
  - approved
  - rejected
  - revise
  - manual fallback

### Core Graph

```text
START
  -> load_candidate_profile
  -> receive_job_input
  -> normalize_job
  -> human_validate_job
  -> analyze_match
  -> human_validate_analysis
  -> generate_application_package
  -> human_review_application
      -> approved -> save_application_package -> update_tracker -> END
      -> revise -> revise_application_package -> human_review_application
      -> rejected -> update_tracker -> END
```

### Acceptance Criteria

- graph can run through the core workflow
- graph does not bypass human validation
- failed automated steps can fall back to manual input
- tracker is updated through workflow state

---

## Phase 7 — Optional Web Search

### Goal

Add online job discovery as an optional input source.

### Implement

- OpenAI Responses API web search wrapper
- search form:
  - target role
  - location
  - required skills
  - limit
- candidate job result list
- user selection
- selected job enters normal intake pipeline

### Source Behavior

Web search only discovers candidate jobs.

It does not apply to jobs, message recruiters, or submit forms.

### Acceptance Criteria

- user can search for jobs online
- app displays candidate jobs
- user can select one job
- selected job becomes a normal tracked job
- selected job goes through the same normalization and validation pipeline

---

## Phase 8 — Optional Assisted Application

### Goal

Help the user apply manually using the generated package.

### Implement

- open apply URL
- show prepared answers
- show cover letter
- show CV tailoring notes
- allow status update to:
  - applied_manually
  - applied_with_agent_assistance

### Not Allowed

- automatic final submission
- login automation
- captcha handling
- LinkedIn scraping
- recruiter messaging automation

### Acceptance Criteria

- app can open the apply URL
- user can copy prepared material
- user can update application status
- tracker records the final state

---

## Suggested File Structure

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
├── tests/
└── skills/
```

---

## Suggested Dependencies

Initial:

```text
streamlit
pydantic
python-dotenv
pytest
```

Later:

```text
openai
langgraph
langchain-core
requests
beautifulsoup4
```

Add dependencies only when the corresponding phase needs them.

---

## Codex Working Pattern

Use one phase per prompt.

Example:

```text
Read AGENTS.md, PROJECT_SPEC.md, and IMPLEMENTATION_PLAN.md.

Implement Phase 1 only.

Do not implement OpenAI calls.
Do not implement web search.
Do not implement LangGraph.
Do not add a database.

After changes, report:
1. files changed
2. how to run
3. what is still missing
```

After each phase:

```bash
pytest
streamlit run app.py
git add .
git commit -m "Implement phase X"
```
