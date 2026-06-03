# Karen Live Workspace Refresh Run Report

Date: 2026-06-03

## Scope

Fixed the Jobs workspace staying stale while Karen workflow runs were active.
This was a frontend/data-refresh change with backend event metadata support.
Workflow business logic, review gates, Browser Use launch behavior, and Karen's
permission model were left unchanged.

## Changes

- Added registry-level refresh metadata for mutating workflow actions.
- Emitted `refresh_scopes` on Karen workflow action events as a top-level field
  and inside event `metadata` and `details`.
- Updated Karen run polling in React to inspect completed workflow action events
  and trigger scoped refreshes for the visible workspace, jobs index/tracker,
  candidate profile, or agent context.
- Added event deduplication so repeated polling responses do not cause reload
  storms.
- Kept a terminal full refresh after a Karen run completes.

## Verification

- `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_karen_workflow_controller.py -q`
- `PATH="$PWD/.conda/bin:$PATH" npm run frontend:test -- frontend/src/App.test.tsx`
- `PATH="$PWD/.conda/bin:$PATH" npm run frontend:typecheck`
- `PATH="$PWD/.conda/bin:$PATH" make verify`

All checks passed.
