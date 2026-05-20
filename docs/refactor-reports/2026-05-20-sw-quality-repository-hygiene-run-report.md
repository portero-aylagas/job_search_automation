# Software Quality Repository Hygiene Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
repository hygiene.

## Findings Addressed

- Runtime CV uploads, generated candidate profile data, and derived exports are
  local artifacts that should stay out of git.
- The ignore rules existed, but there was no explicit safe cleanup command for
  local ignored state.

## Change

- Added `make clean-local-state` to remove ignored runtime state, local
  candidate profile output, and derived exports while preserving tracked sample
  fixtures and `outputs/.gitkeep`.
- Extended privacy/hygiene tests to cover output ignore rules and the cleanup
  target.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `150` pytest tests passed.

## Scope Boundary

This patch intentionally does not address documentation consistency or broader
security hardening. Those remain queued until this repository-hygiene PR is
merged into `main`.
