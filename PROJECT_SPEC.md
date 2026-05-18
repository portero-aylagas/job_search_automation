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
- ingest a job position from URL or pasted text
- normalize the job into a consistent schema
- compare the job against the candidate profile
- generate tailored application material
- keep AI outputs reviewable and editable
- track the status of each application

The system should assist, propose, and generate, but the user remains responsible for validation and final decisions.

---

## Core Workflow

1. User creates or loads candidate profile.
2. User provides a job URL or job description.
3. App extracts and normalizes job information.
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

- if URL extraction fails, user can paste the job text
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
- paste job description
- manual job form
- import structured JSON
- optional web search result import

The core intake mode is:

```text
job URL or job text -> normalized job listing
```

### Job Normalization

The app converts raw job input into a common schema.

Required normalized fields:

- title
- company
- location
- remote policy
- apply URL
- description
- requirements
- responsibilities
- nice-to-have skills
- salary
- posted date
- source
- retrieval mode

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
- pasted job description
- manual job fields
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
- source
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
│   ├── job_001_raw.txt
│   ├── job_001_normalized.json
│   └── job_001_analysis.json
└── applications/
    └── job_001_application_package.json

outputs/
└── job_001/
    ├── cover_letter.md
    ├── cv_tailoring_notes.md
    ├── recruiter_message.md
    └── application_summary.md
```

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
- source
- retrieval_mode
- title
- company
- location
- remote_policy
- apply_url
- description
- requirements
- responsibilities
- nice_to_have
- salary
- posted_date

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
- cover_letter
- cv_tailoring_notes
- recruiter_message
- form_answers
- selected_experience_units
- status

### TrackerRecord

- job_id
- title
- company
- location
- source
- retrieval_mode
- match_score
- status
- created_at
- updated_at
- application_package_path
- notes
