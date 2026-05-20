# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Local Safe Refactor Mode
- Repository: `job_search_automation`
- Branch: `task/56-strengthen-human-review`
- Commit before: `21b0c57`
- Commit after: Pending commit
- Agent: Codex GPT-5
- User approval: User requested the human-in-the-loop safeguard correction and publication through GitHub.

## Scope

- User request: Correct the human-in-the-loop review gate so application requirements stay visible and must be explicitly reviewed before package generation.
- Files inspected: `app.py`, `src/schemas.py`, `tests/test_app.py`, `tests/test_schemas.py`
- Files changed: `app.py`, `src/schemas.py`, `tests/test_app.py`, `tests/test_schemas.py`, and this report.
- Out of scope: Broader workflow refactors, UI redesign, prompt changes, new providers, and persistence schema migrations.

## Characterization

- Existing tests or checks used: Focused app/schema tests plus full-repo `make verify`.
- New characterization added: Requirements now carry a review state, source evidence stays visible in the requirements panel, and package generation blocks until review is complete.
- Manual checklist, if used:
  - Confirm source evidence still appears in the requirements view.
  - Confirm reviewed requirements persist with `review_status="reviewed"`.
  - Confirm package generation rejects unreviewed requirements.

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| Medium | Medium | Source evidence had been moved into the review-action helper, which hid evidence after review and weakened traceability. | Move source evidence rendering back into the requirements display function. | Focused pytest and `make verify` |
| Medium | Low | The review-state transition was only indirectly covered. | Add a pure helper for marking requirements reviewed and test it directly. | `tests/test_app.py` |

## Patch Applied

- Summary: Added `review_status` to `ApplicationRequirements`, exposed a review action in the UI, blocked package generation until requirements are reviewed, restored source evidence rendering to the requirements panel, and added direct tests for the review transition.
- Why this is one patch: The changes all tighten one human-in-the-loop gate and its persistence path.
- Behavior changed: Requirements are now reviewable as a persistent state before package generation can proceed.
- Public API, schema, prompt, or dependency changed: The persisted schema gained a `review_status` field with default `draft`.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_app.py tests/test_schemas.py -q`
- Result: Passed; `36 passed`
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed; ruff checks, compile checks, and `125 passed`
- Failure summary, if any: None
- CI result, if applicable: Not run locally.

## Follow-Up

- Stopped work: None.
- Approval needed: Explicit approval would be needed before any push, PR mutation, or branch cleanup.
- Next smallest useful patch: If you want stronger workflow memory, add an explicit requirements state beyond `draft` and `reviewed` to separate “auto-discovered” from “user-approved.”
