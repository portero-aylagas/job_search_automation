# Software Quality Data Validation Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
data and JSON validation.

## Findings Addressed

- Storage-backed job IDs were plain strings in persisted models even though they
  drive filesystem paths later.
- `job_details.dynamic_fields` accepted arbitrary dictionaries instead of
  validating the required dynamic field shape.

## Change

- Added shared storage identifier validation for job IDs on `JobListing`,
  `TrackerRecord`, `ApplicationRequirements`, and `ApplicationPackage`.
- Added `JobDynamicField` and normalized `job_details.dynamic_fields` through
  that schema.
- Added tests for path-like job IDs, dynamic field normalization, and invalid
  dynamic fields.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `149` pytest tests passed.

## Scope Boundary

This patch intentionally does not address repository hygiene, documentation
consistency, or broader security hardening. Those remain queued until this
data-validation PR is merged into `main`.
