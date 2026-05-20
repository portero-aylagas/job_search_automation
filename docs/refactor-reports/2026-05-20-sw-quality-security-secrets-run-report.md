# Software Quality Security Secrets Run Report

Date: 2026-05-20

## Mode

Local safe refactor mode for the software-quality engineering category:
security and secrets.

## Findings Addressed

- No committed secrets were found during review, and local personal artifacts
  are ignored by git.
- CV and optional-document uploads were constrained by Streamlit widgets, but
  the backend save helpers did not reject empty, oversized, or unsupported file
  types directly.

## Change

- Added backend upload validation for CV and optional-document saves.
- Enforced supported extensions, non-empty uploads, and a 10 MB maximum size.
- Added focused tests for empty, unsupported, oversized, and accepted uploads.

## Verification

Passed:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Result: Ruff passed, compile checks passed, and `155` pytest tests passed.

## Scope Boundary

This patch intentionally avoids AI-quality changes. It only hardens local
software security around uploaded user documents and keeps normal verification
free of live API keys.
