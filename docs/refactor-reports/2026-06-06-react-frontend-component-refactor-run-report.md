# 2026-06-06 React Frontend Component Refactor Run Report

## Scope

Reduced `frontend/src/App.tsx` size and responsibility by extracting the
monolithic React app into feature-level components, Karen-specific hooks, and
shared UI/helpers.

This was a structure-only refactor. It did not change product behavior,
visible labels, API contracts, styling, workflow pages, or tests.

## Changes

- Replaced `frontend/src/App.tsx` with a small entrypoint that renders
  `app/AppShell.tsx`.
- Added `frontend/src/app/` for top-level shell composition, navigation labels,
  and workflow refresh helpers.
- Added feature modules for:
  - `candidateProfile`
  - `jobIntake`
  - `jobs`
  - `tracker`
  - `monitoring`
  - `karen`
- Moved Karen side-panel rendering, state, selected-job sync, chat submission,
  workflow refresh handling, run polling, progress formatting, and panel resize
  helpers under `frontend/src/features/karen/`.
- Moved reusable UI components and frontend helper functions under
  `frontend/src/shared/`.
- Kept `frontend/src/useKarenRunPolling.ts` as a compatibility re-export.

## Verification

- `npm run frontend:typecheck`
- `npm run frontend:test`
- `PATH="$PWD/.conda/bin:$PATH" make verify`

Results:

- Python tests: 345 passed
- Vitest frontend tests: 47 passed
- Frontend production build: passed
- Playwright smoke tests: 4 passed
