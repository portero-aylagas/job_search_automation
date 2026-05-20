# Software Quality Architecture Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
architecture and file structure.

## Finding Addressed

`app.py` mixed Streamlit rendering with reusable workflow state, path lookup,
storage orchestration, review helpers, and package precondition logic. This made
the application entrypoint harder to scan and made non-UI behavior depend on the
UI module.

## Change

- Added `src/app_workflow.py` for UI-independent workflow helpers.
- Moved candidate/job loading, profile saving, package blocker checks,
  requirements review mutation, apply URL review helpers, workflow trace payload
  conversion, and text-line normalization out of `app.py`.
- Left Streamlit rendering and widget session handling in `app.py`.
- Added focused tests for the new module and its Streamlit-independent boundary.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `139` pytest tests passed.

## Scope Boundary

This patch intentionally does not address the next software-quality categories:
function responsibility, error handling, testability gaps, data validation,
repository hygiene, documentation consistency, or security hardening. Those
remain queued until this architecture PR is merged into `main`.
