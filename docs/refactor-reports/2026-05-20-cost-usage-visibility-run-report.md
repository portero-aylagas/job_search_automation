# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Full Automation Mode
- Repository: job_search_automation
- Branch: `task/cost-usage-visibility`
- Commit before: `a7e9084`
- Commit after: pending
- Agent: Codex
- User approval: User requested automation mode for the first cost and usability change.

## Scope

- User request: Implement the first cost and usability visibility improvement.
- Files inspected: `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `app.py`, `src/schemas.py`, `src/llm_client.py`, `tests/test_app.py`, related LLM workflow tests
- Files changed: `app.py`, `tests/test_app.py`, this run report
- Out of scope: Billing analytics, actual provider token accounting, pricing estimates, schema changes, and package editing workflows

## Characterization

- Existing tests or checks used: `PATH="$PWD/.conda/bin:$PATH" make verify`
- New characterization added: App test for AI usage summaries counting calls, provider attempts, retries, output token budgets, worst-case retry budgets, and tool-call caps.
- Manual checklist, if used: Confirmed usage summary is derived from existing `AIWorkflowTrace` objects and does not require live API keys.

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| High | Low | AI traces had useful cost-control metadata, but users had to inspect raw trace details one call at a time. | Add local usage summaries around saved traces and visible pre-action notices for AI/provider workflows. | `PATH="$PWD/.conda/bin:$PATH" make verify` |
| Medium | Medium | The app still does not capture actual provider token usage or billing data. | Add provider usage capture only if the SDK response exposes stable token accounting for structured outputs. | Fake-client tests plus manual provider-contract review |

## Patch Applied

- Summary: Added AI usage summaries for CV parsing, job intake, requirements discovery, and package generation, plus brief UI notices before AI/provider actions.
- Why this is one patch: The change has one purpose: make existing AI usage metadata visible without changing provider behavior or persistence schemas.
- Behavior changed: Users can now see AI call count, provider attempts, retries used, output-token budget, worst-case retry budget, and tool-call cap for completed workflows with traces.
- Public API, schema, prompt, or dependency changed: No.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_app.py -q`
- Result: Passed, 29 tests.
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed, 129 tests.
- Failure summary, if any: First verification run found one line-length lint issue in `app.py`; it was fixed and verification passed.
- CI result, if applicable: pending

## Follow-Up

- Stopped work: None.
- Approval needed: None for this patch.
- Next smallest useful patch: Add deterministic blocked results for requirements discovery when the apply page is empty, blocked, generic, or no longer job-preserving.
