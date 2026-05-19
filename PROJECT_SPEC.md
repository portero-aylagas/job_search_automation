# Project Specification

## Product

Job Search Automation is a Python application for a controlled human-in-the-loop job application workflow.

The core feature is:

```text
candidate profile + job position -> validated application package
```

The application helps a user transform professional data and a specific job position into structured, reviewable application material.

The system can optionally help with job discovery and assisted application steps, but those are extensions. The main pipeline remains centered on generating high-quality application data from a known job position.

---

## Core Problem

Job applications require repeated adaptation of the same professional background to different positions.

The user needs a system that can:

- store structured candidate data
- store reusable experience units
- ingest a job position from a URL with manual review fallback
- normalize the job into a consistent schema
- compare the job against the candidate profile
- generate tailored application material
- keep AI outputs reviewable and editable
- track the status of each application

The system should assist, propose, and generate, but the user remains responsible for validation and final decisions.

---

## Core Workflow

1. User creates or loads candidate profile.
2. User provides a job URL.
3. App extracts and normalizes job-offer information.
4. User validates normalized job data.
5. App analyzes candidate/job match.
6. User validates analysis.
7. App generates application material.
8. User reviews, edits, approves, rejects, or regenerates the package.
9. App saves the final package and updates the tracker.

---

## Design Principles

### Human-in-the-loop

Every important AI-generated output must be:

- visible
- editable
- traceable
- approvable
- rejectable
- repeatable

The user must be able to override the system at every stage.

### Controlled workflow

The workflow should not silently jump from one stage to another without validation.

Examples:

- normalized job data must be validated before match analysis
- match analysis must be validated before application generation
- generated application material must be reviewed before being marked ready
- application submission must not be automatic

### Manual fallback

Every automated step needs a manual fallback.

Examples:

- if URL extraction fails, user can paste or edit the extracted job text
- if job search fails, user can manually add a job
- if AI generation is poor, user can edit or regenerate with feedback
- if assisted application fails, user can apply manually and update the tracker

### Source provenance

Every job and generated artifact should preserve where it came from.

Example retrieval modes:

```text
manual
url
web_search
import
agent
claude_indeed_export
```

---

## Core Scope

### Candidate Profile

The app stores structured candidate information:

- professional summary
- target roles
- target locations
- skills
- languages
- salary expectation
- constraints
- documents used

### Experience Units

The app breaks the candidate’s background into reusable experience units.

An experience unit is a compact, reusable block of evidence.

### Job Intake

Supported intake modes:

- paste job URL
- review and edit extracted job details
- paste job description as a fallback when extraction fails
- import structured JSON
- optional web search result import

The core intake mode is:

```text
job URL -> LLM-assisted extraction -> human review -> normalized job listing
```

The first Job Intake screen should show only the job URL input and an extraction
action. Fixed and dynamic review fields appear only after extraction, because
the user goal is to generate useful application data from a URL rather than fill
out a normalization form manually.

### Job Normalization

The app converts raw job input into a common schema.

Required visible normalized fields:

- title
- company
- source URL

Required internal workflow fields:

- generated app job ID
- retrieval mode

Optional source and role fields:

- source job ID from the external provider
- location
- remote policy
- description
- requirements
- responsibilities
- nice-to-have skills
- salary
- posted date
- apply URL
- flexible job details metadata

The generated app job ID is the stable internal identifier. External job board
IDs are stored only when available as `source_job_id`. `retrieval_mode` records
how the workflow obtained the job and is not shown as an editable UI field.

`apply_url` is optional as job-offer metadata, but it becomes a required workflow
gate before application requirements discovery and package generation. It must
be a real `http` or `https` application action URL. Email addresses, `mailto:`
links, contact people, and phone numbers should be preserved as dynamic job
details, not as `apply_url`.

`job_details` stores dynamic extracted fields that do not fit the fixed schema.
Each dynamic field should preserve at least:

- `dynamic: true`
- `name`
- `value`

It may also preserve metadata such as category, source text, and confidence for
later validation. The UI should show dynamic fields as normal review fields
using the extracted `name` as the label and `value` as the editable value,
without exposing raw JSON to normal users.

Job-offer normalization does not include application-form requirements. Required
documents, motivation-letter prompts, screening questions, and form fields are
captured later in `application_requirements.json` after the system or user
follows `apply_url`.

### Match Analysis

The app compares the normalized job against the candidate profile and experience units.

The output includes:

- match score
- matched skills
- missing skills
- strong experience units
- weak points
- recommended positioning
- application strategy

The score should be deterministic where possible. AI may explain the score, but should not be the only source of scoring logic.

### Application Package Generation

For a selected job, the app generates:

- cover letter draft
- CV tailoring notes
- recruiter message
- application form answers
- application summary
- missing information checklist

The generated package must remain editable and reviewable.

Application packages should be stored as structured JSON with a variable list of
artifacts. Each job can require different materials, such as a CV note, a cover
letter, custom screening answers, portfolio links, or missing-information
prompts. Markdown exports are derived review artifacts and are not the source of
truth.

When present, `application_requirements.json` guides which artifacts and answers
the package generator should create. Package outputs remain separate from both
the normalized job offer and the discovered application-form requirements.

### Review and Approval

Each generated artifact can be:

```text
draft
needs_review
approved
rejected
regenerated
manually_edited
```

The user can:

- approve
- reject
- edit
- regenerate with feedback
- mark as ready to apply

### Application Tracker

The tracker stores the state of each opportunity.

Supported statuses:

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

The tracker should support:

- filtering by status
- sorting by match score
- opening job URLs
- opening generated application material
- editing notes
- updating application state
- exporting data

---

## Optional Extensions

These features are optional and should not block the core workflow.

### Public Web Job Search

The app may use public web search to find candidate job opportunities.

The output of job search should be a list of candidate jobs that the user can review and select.

Selected jobs enter the same normal intake pipeline.

```text
web search -> candidate jobs -> user selection -> normalization
```

### Claude/Indeed Import

The app may support importing structured job data produced externally through Claude and the official Indeed connector.

This is an import path, not a required runtime dependency.

### Assisted Application

The app may open the application URL and provide prepared answers.

The app must not automatically submit applications.

### Job Proposal Agent

The app may suggest jobs based on the user profile.

The user must approve which jobs enter the application pipeline.

---

## Out of Scope

The first version should not implement:

- autonomous final submission
- LinkedIn scraping
- login/session automation
- email sending
- learning from outcomes
- vector database
- full RAG system
- Notion sync
- multi-agent orchestration beyond what is necessary for the workflow
- browser automation as a core dependency

---

## Main UI Pages

### Candidate Profile

Purpose: create, inspect, and edit structured candidate data.

Sections:

- profile summary
- target roles
- target locations
- skills
- languages
- constraints
- salary expectation
- uploaded/source documents
- experience units

### Job Intake

Purpose: add a job position to the system.

Inputs:

- job URL
- extracted job detail review fields
- pasted job description fallback
- optional JSON import

Actions:

- extract job text
- normalize job
- save job
- add to tracker

### Job Analysis

Purpose: compare candidate profile against a selected job.

Displays:

- normalized job data
- match score
- matched skills
- missing skills
- relevant experience units
- weak points
- strategy notes

Actions:

- approve analysis
- edit analysis
- regenerate analysis
- reject job

### Jobs

Purpose: give every tracked opportunity its own workspace.

The Jobs page starts from `data/tracker.json`, lets the user select a tracked
job, and displays the saved intake data from
`data/jobs/<job_id>/normalized_job.json` when available.

Initial displays:

- job title
- company
- status
- match score
- retrieval mode
- source URL
- apply URL
- location and remote policy
- description
- requirements
- responsibilities
- nice-to-have skills
- dynamic extracted details

Later phases can add analysis, package artifacts, application requirements,
notes, history, duplicate resolution, and applied-job management to this same
per-job space.

### Application Generator

Purpose: generate tailored material for an approved job.

Outputs:

- cover letter
- CV tailoring notes
- recruiter message
- form answers
- summary

Actions:

- generate
- edit
- regenerate with feedback
- save draft
- approve package

### Review and Approval

Purpose: control the final validation of generated material.

Actions:

- approve
- reject
- request revision
- manually edit
- mark ready to apply

### Tracker

Purpose: track all jobs and applications.

Displays:

- job title
- company
- location
- source URL
- retrieval mode
- match score
- status
- created date
- updated date
- notes
- application package path

---

## LangGraph Role

LangGraph should be used for workflow orchestration once the basic functionality exists.

The workflow graph should manage:

- state transitions
- approval gates
- revision loops
- fallback paths
- tracker updates

LangGraph should not be introduced before the basic data model, storage, and UI scaffold exist.

---

## Data Storage

The first version should use JSON files.

Suggested structure:

```text
data/
├── profile.json
├── experience_units.json
├── tracker.json
├── jobs/
│   └── job_001/
│       ├── raw_input.txt
│       ├── normalized_job.json
│       ├── analysis.json
│       ├── application_requirements.json
│       ├── application_package.json
│       └── events.jsonl

outputs/
└── job_001/
    └── application_package.md

tests/
└── fixtures/
    └── sample_job_package/
```

The `data/` directory stores runtime application state. The `outputs/`
directory stores derived human-readable exports generated from JSON. Test,
mock, example, and template-style artifacts belong in `tests/fixtures/`, not in
runtime `data/`.

A database can be added later if JSON files become limiting.

---

## Core Entities

### CandidateProfile

- summary
- target_roles
- locations
- skills
- languages
- constraints
- salary_expectation
- documents_used

### ExperienceUnit

- id
- title
- category
- skills
- evidence
- relevance_tags

### JobListing

- id
- title
- company
- source_url
- retrieval_mode
- source_job_id
- location
- remote_policy
- description
- requirements
- responsibilities
- nice_to_have_skills
- salary
- posted_date
- apply_url
- job_details

Only `title`, `company`, and `source_url` are required visible fields. `id` is
generated by the app, and `retrieval_mode` is required internal workflow
metadata hidden from editable UI forms. The remaining fields are optional role
details populated by extraction, import, or human review.

### ApplicationRequirements

- job_id
- source_apply_url
- required_documents
- motivation_letter_required
- screening_questions
- form_fields
- portfolio_fields
- missing_information
- reviewed_by_user

This entity describes requirements discovered from the apply page after
following or inspecting `apply_url`. It is stored separately from
`normalized_job.json` because apply-form requirements are a later workflow stage
than job-offer normalization.

The workflow must stop before this stage if no valid application URL is
available. Follow-up issue #35 tracks stricter reachability validation for this
gate.

### JobAnalysis

- job_id
- match_score
- matched_skills
- missing_skills
- strong_experience_units
- weak_points
- application_strategy

### ApplicationPackage

- job_id
- artifacts
- missing_information
- selected_experience_units
- status

Each artifact should include an id, type, label, required flag, status, and
content. Artifacts that answer job-specific questions should also preserve the
source prompt.

### TrackerRecord

- job_id
- title
- company
- source_url
- location
- retrieval_mode
- match_score
- status
- created_at
- updated_at
- application_package_path
- notes
