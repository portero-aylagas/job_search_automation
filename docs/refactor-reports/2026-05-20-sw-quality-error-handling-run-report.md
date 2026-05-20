# Software Quality Error Handling Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
error handling.

## Findings Addressed

- Malformed JSON failed with a low-context decoder exception instead of a
  path-aware project error.
- Playwright browser fallback failures were swallowed as a generic unavailable
  result, losing the exception class and message needed for diagnosis.

## Change

- Added `JsonStorageError` and wrapped `json.JSONDecodeError` with the failed
  path, line, column, and decoder message.
- Added `BrowserInspectionFailure` so browser fallback absence or runtime
  failure is recorded on the application page snapshot.
- Added focused tests for malformed JSON and browser fallback failure messages.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `141` pytest tests passed.

## Scope Boundary

This patch intentionally does not address testability gaps, data validation,
repository hygiene, documentation consistency, or security hardening. Those
remain queued until this error-handling PR is merged into `main`.
