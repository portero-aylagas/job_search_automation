# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Local Safe Refactor Mode
- Repository: `job_search_automation`
- Branch: `task/extract-llm-client`
- Commit before: `3efe636`
- Commit after: local uncommitted patch
- Agent: Codex GPT-5
- User approval: User asked to proceed with the path-policy refactor before match analysis.

## Scope

- User request: Centralize runtime, template, and output paths that were scattered across app and workflow modules.
- Files inspected: `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `skills/safe_project_improvement_system/SKILL.md`, `src/storage.py`, `src/job_intake.py`, `src/application_package.py`, `src/application_requirements.py`, `src/cv_extraction.py`, `src/sample_data.py`, `app.py`, related tests
- Files changed: `src/paths.py`, `src/storage.py`, `src/job_intake.py`, `src/application_package.py`, `src/application_requirements.py`, `src/cv_extraction.py`, `src/sample_data.py`, `app.py`
- Out of scope: Match analysis, schema changes, persisted data migration, UI changes, dependency changes

## Characterization

- Existing tests or checks used: Full-repo `make verify`
- New characterization added: None; existing storage, app, job intake, requirements, package, CV extraction, and sample-data tests cover the preserved path behavior.
- Manual checklist, if used:
  - Confirm runtime paths still prefer `data/runtime/...`
  - Confirm template fallback paths still read from `data/jobs/...` or `data/*.json`
  - Confirm generated package markdown still writes under `outputs/<job_id>/`
  - Confirm upload paths still write under `data/runtime/candidate_profile/...`

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| High | Medium | Runtime, template, upload, and output paths were duplicated across multiple modules, increasing storage drift risk before match analysis adds more artifacts. | Add `src/paths.py` and route existing path construction through centralized constants and builders. | `PATH="$PWD/.conda/bin:$PATH" make verify` |

## Patch Applied

- Summary: Added `src/paths.py` for central path constants and path builders, then updated app loading, job persistence, requirements saving, package saving/loading, CV uploads, sample data bootstrapping, and storage directory setup to use it.
- Why this is one patch: The single purpose is storage path-policy centralization with existing behavior preserved.
- Behavior changed: No intended product behavior change.
- Public API, schema, prompt, or dependency changed: No schema, prompt, or dependency change. Internal module API expanded with `src.paths`; existing filename constants imported by tests remain available from their previous modules.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed; ruff checks passed and `99 passed`
- Failure summary, if any: Initial lint failures found unused compatibility imports and two long lines; both were fixed before the final passing run.
- CI result, if applicable: Not run locally

## Follow-Up

- Stopped work: Match analysis was not started in this patch.
- Approval needed: Commit, push, and PR updates require explicit user direction.
- Next smallest useful patch: Begin deterministic match analysis using the centralized path helpers for any new match-analysis artifacts.
