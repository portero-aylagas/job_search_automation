# Implementation Plan

## Development Strategy

Build the application incrementally.

The first goal is a working controlled workflow using local sample data and JSON storage.

Do not start new feature phases with web search, browser automation, or external APIs unless the current phase needs them. LangGraph is the intended whole-app orchestration architecture now that the core data model and UI scaffold exist; add only the graph slice needed by the current task.

---

## Current Delivery Status

### Delivered

- Candidate Profile MVP now uses the CV as the source of truth for professional
  data instead of asking the user to rebuild the CV manually.
- The Candidate Profile page supports mandatory CV upload, agent/LLM extraction,
  optional supporting documents, editable extracted CV review fields, manual
  job-search preferences, validation, and JSON persistence.
- CV extraction is implemented through an agent-facing graph/task that uploads
  the CV and asks the LLM for structured `cv_extracted` data. The UI does not
  parse CV content directly.
- Optional documents can be uploaded separately and are parsed into supplemental
  evidence such as references or certificates when available.
- Candidate profile storage now uses `data/candidate_profile.json`; local CV
  uploads and generated candidate-profile data are ignored by git because they
  contain personal CV-derived data.
- Job Intake now resolves `apply_url` through a bounded LangGraph-compatible
  workflow that extracts static candidates from the source page, verifies job
  identity deterministically, records rejected candidates, and uses the older
  LLM resolver only as a fallback candidate generator when no static candidates
  are found.
- Application requirements discovery is implemented as a read-only
  LangGraph-compatible slice that stores page snapshots and interpreted
  requirements for review.
- Application package generation is implemented with manifest-driven artifacts,
  requirement traceability, package quality checks, JSON persistence, Markdown
  export, and manual edit/reject recovery actions.
- Deterministic match analysis exists as historical backend code, but it is
  removed from the active user-facing known-job apply workflow. Existing
  `analysis.json` files are ignored by normal navigation, Karen, package
  generation, and tracker progression.
- Karen is implemented as the runtime product assistant for the current
  human-gated workflow. Her chat now appears as a persistent app-level side
  panel with selected-job context, pending-gate hints, persisted session
  transcripts, job-scoped copies, structured event logs, and explicit workflow
  permission flags. The top-level `Agent Karen` tab remains as a dashboard for
  workflow status, blockers, timeline, and static next-action guidance. With
  explicit permission, Karen can run registered job-scoped workflow actions and
  launch Browser Use apply assistance; final submission, login, MFA, captcha,
  account creation, recruiter messaging, and invented candidate data remain out
  of scope.
- The primary UI has been migrated from Streamlit to React + TypeScript + Vite
  with a thin FastAPI adapter over the existing Python workflow functions. The
  first React version is a parity port: it preserves top-level navigation,
  button labels, structured review forms, review gates, and Browser Use launch
  semantics.
- The React UI uses `assets/karen.png` for Karen's page portrait and browser
  tab icon. Fresh local state is supported through the API returning an empty
  draft candidate profile when private runtime files have been cleaned.

### Not Delivered Yet

- Public web job discovery is still pending.
- Broader duplicate handling and a proper applied-jobs view are still pending.
- One-command local startup for FastAPI + Vite is still pending.
- A production hosting decision for the React build is still pending.
- Complex nested CV editors, multiple CV versions, excluded roles, excluded
  companies, profile scoring, passport/ID upload, and job matching from the
  Candidate Profile page remain out of scope.

### Requirement Changes From Candidate Profile MVP

- Candidate professional data now comes from `cv_extracted`, populated by CV
  extraction and editable by the user.
- Manual candidate preferences are optional job-search metadata and are not
  required for known-job applications: target roles, target locations, remote
  preference, employment type, career level, availability, annual EUR salary
  range, and EU work authorization.
- `remote_preference` no longer includes `no_preference`; users select all
  concrete modes when they are open to all.
- `employment_type` is separate from career level and contains only work
  arrangement values: full-time, part-time, contract, and freelance.
- Career level is stored as `seniority_level` for compatibility but shown as
  `Career level`, with per-option hover help in the UI.
- Salary expectation is stored as `salary_min_eur` and `salary_max_eur`, both
  annual EUR integer values.
- Work authorization is EU-only for now: EU authorized or EU sponsorship
  required.
- Application rules are not part of the Candidate Profile UI or JSON schema;
  they remain fixed product behavior outside this profile form.

---

## Phase 1 — Project Scaffold

### Goal

Create the minimum runnable application structure.

### Create

```text
frontend/src/App.tsx
src/api.py
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
- FastAPI app
- React app navigation
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
PATH="$PWD/.conda/bin:$PATH" uvicorn src.api:app --host 127.0.0.1 --port 8001 --reload
npm run frontend:dev
```

- sample profile is visible
- sample experience units are visible
- sample tracker table is visible
- JSON helpers can save and load data
- no live API calls are required

---

## Phase 1A — Candidate Profile MVP

### Goal

Let the user create a candidate profile from a CV, with optional job-search
preferences that are not required for known-job applications.

### Implemented

- mandatory CV upload
- CV file storage under local runtime data
- agent-facing CV extraction task using a LangGraph-compatible graph:
  `inspect_cv_document_agent -> extract_cv_data`
- LLM structured extraction into:
  - identity
  - work experience
  - education
  - skills
  - languages
  - certifications
  - projects
- optional supporting document upload and supplemental extraction into
  references, certifications, and other evidence
- editable CV-extracted review section with required reviewed identity fields:
  first name, surname, gender, email, phone, address, postal code, city,
  country, and nationality
- canonical reviewed gender values:
  `Male`, `Female`, and `Diverse`
- salutation is not stored as a primary identity field; legacy salutation input
  is migrated into reviewed gender
- optional supporting documents are parsed through the same review workflow and
  merged into the reviewable candidate profile state
- optional manual candidate preferences:
  - target roles
  - target locations
  - remote preference
  - employment type
  - career level
  - availability
  - annual EUR salary range
  - EU work authorization
- section-level save actions for reviewed CV fields and optional preferences
- workflow readiness validation through downstream blockers
- JSON persistence to `data/candidate_profile.json`

### Data Output

```text
data/candidate_profile.json
data/runtime/candidate_profile/cv/<timestamp>-<uploaded-file>
```

### Acceptance Criteria

- user must upload a CV before saving a complete profile
- CV extraction is triggered through the agent layer, not by UI regex parsing
- extracted CV data is visible and editable before saving
- reviewed identity data must include gender before the profile can be saved
- user can fill job-search preferences manually, but they are optional
- employment type is an optional checkbox list
- career level is a checkbox list with hover help for each option
- work authorization is an optional mutually exclusive EU radio choice
- salary is an optional yearly EUR min/max range and max must be greater than
  or equal to min when both values are present
- reviewed CV fields and optional preferences are saved through their own
  section actions
- downstream workflow readiness is validated by blockers against the persisted
  candidate profile data
- local personal profile artifacts are not committed to git
- optional supporting documents can be saved and merged into the reviewable
  candidate profile data

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

Disabled from the current known-job workflow. Existing backend code and saved
`analysis.json` files may remain temporarily, but match analysis is no longer a
gate before requirements discovery or package generation.

### Future/Disabled Scope

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

- current app navigation does not require match analysis
- Karen does not propose `analyze_match`, `review_match`, or `reject_match`
- package generation can proceed from reviewed requirements without reviewed
  match analysis
- existing saved `analysis.json` files remain compatible historical artifacts

---

## Phase 4 — Apply Requirements Discovery and Application Package Generation

### Goal

Inspect a validated `apply_url` first, store the application contract for human
review, then generate application material from candidate profile + experience
units + job data guided by those requirements.

### Implement

- initial read-only LLM/agent application-requirements discovery from `apply_url`
- LangGraph requirements-discovery slice:
  `application page inspection -> requirements extraction`
- read-only `inspect_application_page_agent` node that gathers a structured
  apply-page snapshot before LLM interpretation
- validate that `apply_url` is usable before requirements discovery
- stop requirements discovery when `apply_url` is missing, invalid, unreachable,
  points back to the job-offer page, or does not preserve the selected job
- use the LLM/agent to interpret multilingual, ATS-specific, and dynamic apply
  pages; local code must not infer requirements through fixed regex or
  hard-coded form heuristics
- preserve job-preserving resolution evidence and rejected candidates for review
- preserve human review of discovered application requirements
- store required documents, upload expectations, file constraints, screening
  questions, custom form fields, requested profile fields, cover-letter or
  motivation-letter requirements, consent requirements, privacy/login/ATS gates,
  deadlines, contact/fallback information, missing items, source evidence, and
  confidence
- OpenAI API wrapper
- prompt templates
- manifest-driven application artifact generation
- support for variable job-specific materials
- application form answer generation
- markdown package rendering from JSON
- application package save/load
- apply URL validation that rejects source-page URLs, non-http(s) targets, and
  other invalid application destinations before jobs are saved
- package generation gate that requires a complete known-job candidate profile,
  parsed CV, parsed job description, and reviewed job-preserving application
  requirements before generating application material

### Generated Outputs

```text
data/jobs/<job_id>/application_page_snapshot.json
data/jobs/<job_id>/application_requirements.json
data/jobs/<job_id>/application_package.json
data/jobs/<job_id>/application_fill_plan.json
outputs/<job_id>/application_package.md
```

`application_requirements.json` is the first Phase 4 output contract. It is
created from a stored `application_page_snapshot.json` by an LLM interpretation
step and remains
read-only with respect to package generation: no cover letter, generated
answers, or final package is created by this discovery step.

The package JSON is the source of truth. Markdown output is a derived review or
export file generated from the full package.
`normalized_job.json` describes the job offer. `application_requirements.json`
describes required documents, motivation letter needs, screening questions, and
form fields discovered later from `apply_url`. `application_fill_plan.json` is
the reviewed execution contract for Browser Use and remains separate from the
read-only requirements contract.

### Acceptance Criteria

- user can select a saved reviewed job with a valid `apply_url`
- app can record application requirements when an apply URL is available
- unreachable, missing, email-only, same-page, or generic career-page apply URLs
  block requirements discovery
- application requirements are saved separately from `normalized_job.json`
- UI displays discovered application requirements clearly for review
- app generates an application package
- package generation uses `application_requirements.json` when present
- generated material is visible in UI
- package is saved
- app generates an editable application fill plan from reviewed requirements,
  reviewed package content, and safe candidate profile data
- fill-plan generation uses deterministic identity/contact mapping first, then
  an AI semantic mapper for remaining non-sensitive fields
- reviewed gender can map salutation fields such as `Frau`, `Herr`, `Divers`,
  `Mr`, `Ms`, or `Mx` when the target application page offers those options
- Browser Use apply assistance is blocked until every discovered application
  field is reviewed into an explicit value or intentional blank
- tracker status can move to `application_draft`

### Current Browser Use Pilot

- Browser Use is currently wired only into the Jobs `Apply Assistance` panel,
  not Job Intake.
- The current pilot scope is benchmarking guarded browser interaction on real
  application pages, not autonomous submission.
- Each run starts a fresh local Browser Use process with an isolated Chromium
  profile and local reset controls.
- Browser Use receives only the reviewed application fill plan: explicit field
  values, reviewed upload paths, and submit guard labels. Any unresolved
  consent, referral, disability, or other blocked field keeps the fill plan in
  draft and prevents the Browser Use run from starting.
- The Browser Use task order is intentionally simple: fill or confirm reviewed
  pre-upload fields, process mandatory checkboxes exactly once, then upload all
  reviewed files last. Uploads are blocked until field and mandatory checkbox
  rows are complete or explicitly failed.
- The browser agent does not receive raw candidate profile JSON and remains
  guarded against proceeding to review or submission.
- Final submission remains out of scope and blocked by explicit agent/task
  guardrails.

### Follow-up Tickets

- #34 implements apply-page requirements discovery as the current core Phase 4
  task using the first LangGraph slice: snapshot-first page inspection followed
  by requirements extraction.
- #35 validates `apply_url` reachability and job-identity preservation before downstream workflow continues.
- #36 adds source-grounding checks for AI-extracted content and rejected apply-link candidates to reduce hallucinated or unsupported fields.
- #27 generates the later application package from reviewed job, candidate, and
  application-requirements data.
- #28 adds downstream human review work for generated material.
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

Expand the existing graph pattern into the full workflow state machine.

### Implement

- `WorkflowState`
- LangGraph nodes:
  - load_candidate_profile
  - receive_job_input
  - normalize_job
  - human_validate_job
  - inspect_application_page_agent
  - extract_application_requirements
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
  -> inspect_application_page_agent
  -> extract_application_requirements
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

### Recommended Discovery Stack

Use a hybrid background pipeline rather than a free-running autonomous agent:

```text
daily deterministic runner
  -> load reviewed candidate profile
  -> build sanitized search profile
  -> generate public web-search queries
  -> collect candidate job URLs
  -> extract lightweight job facts with structured AI output
  -> filter duplicates, stale pages, and hard preference mismatches
  -> score candidates deterministically
  -> propose one job for user review
```

The deterministic Python layer should own scheduling, query templates, URL
normalization, duplicate detection, already-seen accepted/rejected checks,
location and remote-policy filtering, salary/seniority hard filters, one-job
daily limits, JSON persistence, and tracker handoff.

Use the LLM only at controlled boundaries where public web data is messy:

- turn search result snippets or fetched pages into structured candidate jobs
- extract lightweight title, company, location, remote policy, salary, skills,
  seniority, and freshness signals
- decide whether a result is probably a real job post
- explain match reasons and uncertainty for the user-facing proposal

Discovery should store lightweight candidates separately from normalized jobs.
Suggested runtime files:

```text
data/runtime/discovery_runs/<date>.json
data/runtime/discovery_candidates.json
```

Accepted candidates enter the existing Job Intake pipeline with
`retrieval_mode="web_search"`. Rejected candidates remain in discovery history
so the same job is not proposed again. Application package generation and
Browser Use apply assistance remain downstream human-gated workflows.

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

- final submission through Karen
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
├── package.json
├── vite.config.ts
├── index.html
├── frontend/
├── src/
│   ├── __init__.py
│   ├── api.py
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
├── tests/
└── skills/
```

---

## Suggested Dependencies

Initial:

```text
fastapi
uvicorn
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
Do not expand LangGraph beyond the requested phase.
Do not add a database.

After changes, report:
1. files changed
2. how to run
3. what is still missing
```

After each phase:

```bash
pytest
npm run frontend:typecheck
git add .
git commit -m "Implement phase X"
```
