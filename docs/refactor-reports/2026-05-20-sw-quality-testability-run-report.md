# Software Quality Testability Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
testability.

## Finding Addressed

The job URL extraction path was only callable through Streamlit-oriented code,
which made the extraction/resolution orchestration harder to verify without UI
state or live AI/network services.

## Change

- Added `extract_job_intake_data` in `src/app_workflow.py`.
- Added injectable extractor and apply URL resolver callables for fake-client
  tests.
- Updated `app.py` to call the workflow helper and only handle Streamlit
  session state there.
- Added a focused fake-based regression test for the extraction/resolution
  contract.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `142` pytest tests passed.

## Scope Boundary

This patch intentionally does not address data validation, repository hygiene,
documentation consistency, or security hardening. Those remain queued until
this testability PR is merged into `main`.
