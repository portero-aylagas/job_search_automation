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
job URL or job description
    ↓
normalized job listing
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
- job URL or job description intake
- job normalization
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
│   ├── tracker.json
│   ├── jobs/
│   └── applications/
├── outputs/
├── tests/
└── skills/
```

The `skills/` directory contains development-support skills used during implementation and project improvement. It is not part of the runtime application unless explicitly integrated.

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

- cover letter
- CV tailoring notes
- recruiter message
- form answers
- selected experience units
- package status

### Tracker Record

Application tracking information:

- job ID
- title
- company
- location
- source
- retrieval mode
- match score
- status
- notes
- generated package path

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
OPENAI_API_KEY=your_api_key_here
```

The application should still support non-AI sample/demo flows without requiring an API key during early phases.

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
