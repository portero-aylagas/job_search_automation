# Sprint 1 Planning

Sprint length: 1 week

Sprint goal: Build a first usable version of a controlled human-in-the-loop job application workflow, with enough planning, reliability, and documentation to satisfy the Ironhack project requirements.

## User Stories

### Story 1 - Application Preparation

As a job applicant
I want to turn a candidate profile and job position into a validated application package
So that I can prepare tailored applications faster without losing control over the final result

### Story 2 - Opportunity Discovery and Tracking

As a job applicant
I want to discover, review, and track job opportunities
So that I can focus on relevant applications and keep a record of what happened

### Story 3 - Project Delivery

As a student
I want a working, documented, and testable project
So that I can demonstrate the technical workflow and the planning process clearly

## Priorities

Core scope:

- candidate profile and reusable experience data
- local JSON storage
- URL-only LLM-assisted extraction with manual review fallback
- normalized job data
- match analysis
- application package generation
- reviewable UI and tracker
- basic reliability and documentation

Add-ons:

- public job search through API, MCP, or web search
- LangGraph orchestration
- assisted application support
- richer CI and quality automation

Out of scope:

- automatic final job submission
- login automation
- captcha handling
- LinkedIn scraping
- recruiter messaging automation

## Sprint Tasks

### 1. Research, Scope & Sprint Plan

- Estimate: 2
- Priority: High
- Dependencies: none

Tasks:

- choose target use case and product scope
- define the core workflow and add-ons
- choose the implementation approach
- identify candidate tools and APIs
- create user stories and sprint tasks
- add estimates, dependencies, and definitions of done

Definition of done:

- GitHub Project board exists
- sprint backlog is documented
- core scope and add-ons are separated
- initial tool/API options are identified

### 2. Research Foundation

- Estimate: 3
- Priority: High
- Dependencies: Research, Scope & Sprint Plan

Tasks:

- choose the baseline job intake path
- decide whether discovery uses API, MCP, or web search
- document expected API costs, limits, and authentication needs
- define the report/application output structure

Definition of done:

- URL-only LLM-assisted extraction with manual review fallback is confirmed as the baseline
- discovery approach is selected or clearly marked as optional
- required environment variables are listed
- output structure is documented

### 3. Environment, Quality Skill & Basic CI

- Estimate: 3
- Priority: Medium
- Dependencies: Research, Scope & Sprint Plan

Tasks:

- standardize local execution on `./.conda`
- document the safe project improvement skill as development support
- add a minimal verification command
- add a basic GitHub Actions CI workflow if time allows

Definition of done:

- environment convention is documented
- quality/refactoring support is documented as non-runtime
- local verification command is defined
- CI exists or is explicitly deferred

### 4. App Scaffold, Schemas & JSON Storage

- Estimate: 5
- Priority: High
- Dependencies: Research Foundation

Tasks:

- create the Streamlit app scaffold
- define candidate, experience, job, analysis, package, and tracker schemas
- add sample data
- add JSON load/save helpers
- show candidate profile and tracker pages

Definition of done:

- app runs locally
- sample candidate data is visible
- sample tracker data is visible
- JSON helpers can save and load data

### 5. Job URL Intake & Normalization

- Estimate: 5
- Priority: High
- Dependencies: App Scaffold, Schemas & JSON Storage

Tasks:

- add first-screen Job URL intake with no manual detail fields before extraction
- extract role details into a review form with an LLM or agent
- add manual review fallback fields
- normalize job data into the shared schema
- save normalized jobs locally
- update the tracker with new jobs

Definition of done:

- user can add a job from a URL
- title, company, and source URL are the required visible job fields
- retrieval mode and the generated app job ID are saved internally but not shown as editable UI fields
- source job ID is optional when the job source exposes one
- dynamic extracted details are shown as normal name/value review fields and saved with metadata
- apply URL is resolved as a job-preserving HTTP(s) workflow gate before downstream steps
- normalized job JSON is saved
- tracker shows the new job

The market-pattern baseline is: normalize the public job-offer page first, then
discover apply-page requirements later from `apply_url`. The apply-link
resolver must reject the original job page, mailto links, and generic career
pages when they do not preserve the specific job identity.

### 6. Job Search / Discovery Integration

- Estimate: 5
- Priority: Medium
- Dependencies: Job URL Intake & Normalization

Tasks:

- implement a small search/discovery path using API, MCP, or web search
- show candidate jobs for user review
- let selected jobs enter the normal intake pipeline
- keep manual review fallback available

Definition of done:

- at least one discovery method can produce candidate jobs
- user can select a discovered job
- selected job follows the same normalization flow
- failures can fall back to manual entry

### 7. Match Analysis & Prioritization

- Estimate: 3
- Priority: High
- Dependencies: Job URL Intake & Normalization

Tasks:

- implement deterministic skill overlap
- compare role, location, and constraints
- calculate a simple match score
- identify matched skills, missing skills, and relevant experience units

Definition of done:

- user can select a saved job
- match analysis is displayed
- analysis is saved locally
- tracker can show analyzed status or score

### 8. Application Requirements Discovery & Package Generation

- Estimate: 5
- Priority: High
- Dependencies: Match Analysis & Prioritization

Tasks:

- add LLM wrapper or template fallback
- discover or record apply-page requirements from `apply_url`
- save application requirements in `data/jobs/<job_id>/application_requirements.json`
- keep discovered requirements human-reviewable
- generate a manifest-driven application package
- support variable job-specific materials and application answers
- save package outputs locally

Definition of done:

- required documents, motivation letter needs, screening questions, and form fields can be captured separately from job-offer normalization
- selected job can produce an application package
- package generation uses `application_requirements.json` when available
- package material is visible in the UI
- package is saved as JSON, with optional Markdown export
- missing information checklist is included

### 9. UI Review, Tracker & Application Logging

- Estimate: 5
- Priority: High
- Dependencies: Application Package Generation

Tasks:

- add review/edit UI for generated material
- add approve, reject, and ready-to-apply statuses
- log application status changes
- track applications that were prepared, applied manually, or assisted

Definition of done:

- generated material can be reviewed
- tracker status can be updated
- application history is persisted
- application outcomes can be inspected later

### 10. LangGraph Workflow Orchestration

- Estimate: 5
- Priority: Medium
- Dependencies: UI Review, Tracker & Application Logging

Tasks:

- define workflow state
- add nodes for intake, validation, analysis, generation, review, and tracker update
- preserve human validation gates
- add manual fallback branches

Definition of done:

- workflow can run through the core path
- validation gates are not bypassed
- failed automated steps can fall back to manual input
- tracker updates through workflow state

### 11. Assisted Application Flow

- Estimate: 3
- Priority: Low
- Dependencies: UI Review, Tracker & Application Logging

Tasks:

- open or expose the apply URL
- show prepared answers beside the application package
- allow the user to mark applied manually or assisted
- avoid automatic final submission

Definition of done:

- user can access the apply URL
- prepared material is easy to copy or review
- tracker records applied status
- no login automation or final submission is automated

### 12. End-to-End Testing & Reliability

- Estimate: 3
- Priority: High
- Dependencies: App Scaffold, Job Intake, Application Package Generation

Tasks:

- run the full workflow with realistic inputs
- add validation, retry, or fallback behavior where needed
- test tool outputs independently and together
- generate sample application outputs

Definition of done:

- core workflow completes end to end
- errors have clear messages or fallbacks
- sample outputs exist
- known bugs are fixed or documented

### 13. Final Polish & Presentation

- Estimate: 3
- Priority: High
- Dependencies: End-to-End Testing & Reliability

Tasks:

- complete README and setup instructions
- create architecture or workflow documentation
- confirm planning board and `docs/stories.md` are complete
- prepare demo video or presentation path
- submit the repository

Definition of done:

- README explains how to run the project
- architecture and workflow are documented
- final verification has been run
- demo path is clear

## Current Development Status

Completed in the current branch:

- Phase 2 direction changed from form-first intake to URL-only LLM-assisted extraction.
- Job Intake first screen now shows only the job URL and extraction action.
- Extracted fields appear in a human review form only after AI extraction.
- Dynamic extracted details are displayed as normal name/value fields and saved in `job_details.dynamic_fields`.
- `apply_url` is blocked if missing, not an `http(s)` URL, or not job-preserving.
- Tracker and Jobs now read from the shared `data/runtime/jobs.json` index.

Open follow-ups:

- #35: stricter apply URL reachability and job-identity validation before downstream workflow steps.
- #36: source-grounding checks for hallucinated or unsupported AI extraction content, including rejected apply-link candidates.
- #37: duplicate management and a proper applied-jobs tracker view.
