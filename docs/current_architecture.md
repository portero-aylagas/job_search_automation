# Current Architecture

This project now uses a React + FastAPI architecture for the primary UI while
keeping the existing Python workflow modules as the source of business logic.
The migration is a UI-platform refactor, not a workflow redesign.

## Runtime Shape

```text
React + TypeScript + Vite
        |
        | JSON API
        v
FastAPI adapter (`src/api.py`)
        |
        | calls existing workflow functions
        v
Python domain modules, Pydantic schemas, JSON storage, LangGraph slices,
Browser Use launcher, and safety gates
```

The FastAPI layer should stay thin. It validates request payloads, translates
React form state into existing Pydantic models, calls the current workflow
functions, and returns JSON for the frontend. It should not duplicate workflow
rules already owned by modules such as `app_workflow.py`,
`application_requirements.py`, `application_package.py`,
`application_fill_plan.py`, or `browser_use_launcher.py`.

## UI Contract

The React UI preserves the Streamlit navigation and workflow semantics:

- `Candidate Profile`
- `Job Intake`
- `Jobs`
- `Tracker`
- `Agent Karen`

Karen chat remains mounted as an app-level side panel across all top-level
pages. The top-level `Agent Karen` page remains as a dashboard for selected-job
workflow status, blockers, timeline, and next-action guidance. Buttons that
invoke AI keep visible `with AI` labels. Review gates remain explicit and
human-controlled. Dynamic job fields, application requirements, package
artifacts, and fill plans remain structured editable forms rather than raw JSON
editors.

The parity checklist for the migration lives in `docs/ui_migration_parity.md`.

## Agent Karen

Karen is a runtime product assistant. She is separate from `AGENTS.md`, which
is development-agent guidance for repository work.

Karen's runtime code lives under `src/agents/karen/`:

- `agent_card.yaml` describes her runtime role and boundaries.
- `prompts.yaml` stores her assistant prompts.
- `policy.py` defines allowed and blocked intents.
- `tools.py` builds workflow context and tool responses.
- `state.py` defines her state models.
- `graph.py` runs each chat turn.

The UI uses `assets/karen.png` for Karen's side-panel portrait, dashboard
portrait, and browser tab icon. Chat transcripts are stored under
`data/runtime/agent_sessions/<session_id>/`. Job-scoped copies and workflow
events are stored under `data/runtime/jobs/<job_id>/`.

Karen can explain the app, inspect workflow state, identify blockers, suggest
next steps, and route the user to the right top-level page. She does not bypass
candidate profile, job, requirements, package, fill-plan, Browser Use, or final
submission gates.

## Local Development

Start FastAPI:

```bash
PATH="$PWD/.conda/bin:$PATH" uvicorn src.api:app --host 127.0.0.1 --port 8001 --reload
```

Start Vite:

```bash
npm run frontend:dev
```

Open `http://127.0.0.1:5173/`.

In Vite development, the frontend calls `http://127.0.0.1:8001` by default.
Set `VITE_API_BASE_URL` to override the API origin. Production builds use
same-origin API paths unless an override is provided.

## Fresh Local State

`make clean-local-state` removes private/runtime files:

- `data/runtime/`
- `data/candidate_profile.json`
- generated output artifacts under `outputs/`

The tracked template files under `data/` remain in the repository. After a
clean start, `GET /api/candidate-profile` returns an empty draft profile rather
than requiring a seed profile file.

## Verification

Use:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

This runs Python linting, Python compile checks, pytest, frontend typecheck,
and frontend build.
