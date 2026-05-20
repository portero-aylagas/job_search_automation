# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Full Automation Mode
- Repository: `job_search_automation`
- Branch: `task/extract-llm-client`
- Commit before: `01decd8`
- Commit after: pending commit for structured-output hardening
- Agent: Codex GPT-5
- User approval: Safe refactor, documentation, publish, and merge work was explicitly requested.

## Scope

- User request: Improve all structured-output audit findings, document the refactor, and publish it through the repository workflow.
- Files inspected: `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `README.md`, `src/cv_extraction.py`, `src/llm_job_extraction.py`, `src/schemas.py`, `tests/test_cv_extraction.py`, `tests/test_application_requirements.py`, `tests/test_application_package.py`
- Files changed: `README.md`, `src/cv_extraction.py`, `src/llm_job_extraction.py`, `tests/test_cv_extraction.py`, `tests/test_llm_job_extraction.py`
- Out of scope: Prompt redesign, provider changes, UI changes, dependency changes, CI changes

## Characterization

- Existing tests or checks used: focused CV/job extraction tests plus full-repo `make verify`
- New characterization added:
  - CV extraction tests now assert the LLM-only response models and normalization behavior.
  - A new job extraction test file checks confidence-schema constraints and normalization into persisted models.
- Manual checklist, if used:
  - Confirm persisted models are no longer used as LLM response schemas for CV and job extraction
  - Confirm missing or optional LLM fields normalize safely into persisted defaults
  - Confirm job extraction confidence is constrained to the shared confidence enum
  - Confirm full local verification passes without live API keys

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| Low | Medium | CV and job extraction used persisted models directly as LLM response schemas, which blurred missing-vs-empty semantics. | Add LLM-only response models with optional fields and normalize them before persistence. | `PATH="$PWD/.conda/bin:$PATH" make verify` |
| Low | Low | Job extraction confidence accepted arbitrary strings. | Constrain persisted confidence to the shared `ConfidenceLevel` type and validate it through the LLM-safe schema. | `PATH="$PWD/.conda/bin:$PATH" make verify` |
| Low | Low | Structured-output tests were lighter for CV and job extraction than for requirements and package generation. | Extend CV extraction tests and add dedicated job extraction schema tests. | `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_cv_extraction.py tests/test_llm_job_extraction.py -q` |

## Patch Applied

- Summary: CV extraction and job extraction now parse into LLM-only response schemas, normalize those responses into persisted models, constrain job extraction confidence to the shared confidence enum, and add schema-focused regression tests for both paths.
- Why this is one patch: The patch has one purpose, which is hardening structured-output handling at the AI boundary without changing the surrounding workflow.
- Behavior changed: Weak or partial model responses are normalized explicitly at the boundary instead of relying on permissive persisted-model defaults during parsing.
- Public API, schema, prompt, or dependency changed: Internal parsing contracts changed for the CV and job extraction modules. No persisted JSON schema or dependency changed.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_cv_extraction.py tests/test_llm_job_extraction.py -q`
- Result: Passed (`10 passed`)
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed (`111 passed`)
- Failure summary, if any: None
- CI result, if applicable: GitHub PR checks are expected after push and merge.

## Follow-Up

- Stopped work: None
- Approval needed: None for commit, push, PR, or merge because publish work was explicitly requested.
- Next smallest useful patch: Apply the same explicit missing-vs-empty distinction to any future LLM-backed extraction flows before they grow new persisted fields.
