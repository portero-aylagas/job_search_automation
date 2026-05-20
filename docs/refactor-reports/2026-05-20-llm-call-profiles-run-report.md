# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Local Safe Refactor Mode
- Repository: `job_search_automation`
- Branch: `task/extract-llm-client`
- Commit before: `2961e5b`
- Commit after: Pending commit
- Agent: Codex GPT-5
- User approval: User requested implementation of the provided LLM/API integration hardening plan.

## Scope

- User request: Harden the LLM/API integration policy by routing each AI workflow through an explicit call profile.
- Files inspected: `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `README.md`, `src/llm_client.py`, LLM workflow modules, and related tests.
- Files changed: `src/llm_client.py`, AI workflow call sites, LLM boundary tests, workflow fake-client tests, `README.md`, and this report.
- Out of scope: New providers, per-workflow model environment variables, prompt rewrites, UI changes, and live API calls.

## Characterization

- Existing tests or checks used: Focused LLM workflow tests plus full-repo `make verify`.
- New characterization added: Unit coverage for structured request parameters, retry/non-retry behavior, missing API-key handling, SDK retry disabling, upload timeout/retry policy, and named workflow profile selection.
- Manual checklist, if used:
  - Confirm all `parse_structured_response(...)` call sites pass a named profile.
  - Confirm direct provider calls remain isolated to `src/llm_client.py`.
  - Confirm the default model remains `OPENAI_MODEL`.

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| High | Medium | LLM calls shared a provider boundary but did not make workflow-specific model behavior visible. | Add `LLMCallProfile` constants and require every structured call to pass a profile. | Focused pytest and `make verify` |
| Medium | Medium | SDK retries were implicit and could duplicate project retries invisibly. | Create `OpenAI(max_retries=0)` and add explicit retry handling in `src/llm_client.py`. | `tests/test_llm_client.py` |
| Medium | Low | File uploads did not expose timeout/retry policy. | Add upload timeout and one retry for transient upload failures. | `tests/test_llm_client.py`, CV extraction fake-client test |

## Patch Applied

- Summary: Added explicit deterministic and creative call profiles, request timeouts, token budgets, disabled truncation, bounded tool-call limits, visible retry policy, upload timeout/retry policy, and tests proving the request contract.
- Why this is one patch: The changes all harden the same provider boundary and its existing call sites without changing product scope.
- Behavior changed: Live LLM requests now include explicit profile parameters and retry only transient failures according to project policy.
- Public API, schema, prompt, or dependency changed: No dependency, persisted schema, or prompt changes. Internal `parse_structured_response(...)` now requires a profile argument.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_llm_client.py tests/test_project_artifacts.py tests/test_cv_extraction.py tests/test_llm_job_extraction.py tests/test_application_requirements.py tests/test_application_package.py tests/test_apply_url_resolution.py -q`
- Result: Passed; `62 passed`
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed; ruff checks, compile checks, and `121 passed`
- Failure summary, if any: None
- CI result, if applicable: Not run locally.

## Follow-Up

- Stopped work: None.
- Approval needed: Explicit approval would be needed before any push, PR mutation, or branch cleanup.
- Next smallest useful patch: Add provider-level telemetry counters if future debugging shows retry behavior needs operational visibility.
