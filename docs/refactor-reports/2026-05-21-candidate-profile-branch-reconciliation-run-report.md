# Safe Improvement Run Report

## Metadata

- Date: 2026-05-21
- Mode: Full Automation Mode
- Repository: `job_search_automation`
- Branch: `task/0-browser-use-base`
- Commit before: `349a800`
- Commit after: pending commit for branch reconciliation and candidate profile rescue
- Agent: Codex GPT-5
- User approval: Commit, documentation, merge to `main`, and GitHub issue creation were explicitly requested.

## Scope

- User request: Rescue missing candidate-profile work, reconcile repeated UI work across branches/worktrees, document the incident, merge the result into `main`, and open follow-up GitHub issues.
- Files inspected: `src/candidate_profile_ui.py`, `src/cv_extraction.py`, `src/prompts.yaml`, `src/schemas.py`, `src/candidate_profile.py`, `tests/test_cv_extraction.py`, git branch/worktree history
- Files changed: candidate profile UI, CV extraction helpers, prompt text, candidate profile validation/schema files already in progress on the task branch, and characterization tests for CV review formatting
- Out of scope: Browser Use behavior changes, new product features beyond the candidate-profile and reconciliation work, branch deletion

## Characterization

- Existing tests or checks used: focused candidate-profile, CV extraction, schema, app, fill-plan, and workspace pytest runs plus full-repo `make verify`
- New characterization added:
  - Added `tests/test_candidate_profile_ui.py` to lock the extracted-review formatting helpers and adaptive text-area sizing.
  - Added CV extraction normalization coverage for work-experience review blocks and bullet cleanup.
- Manual checklist:
  - Confirm `main`-only candidate-profile commits exist in a separate worktree
  - Confirm the task branch lacked those commits in its ancestry
  - Confirm extracted review is rendered as section `2`
  - Confirm work experience is preserved as editable review blocks
  - Confirm mandatory first name, surname, contact, address, and nationality fields still validate correctly

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| High | Medium | Candidate-profile UI formatting work was committed on `main` in a separate worktree and was not present in `task/0-browser-use-base`, which caused repeated implementation and risk of feature regression. | Reconcile the branches by restoring the `main` formatting behavior on top of the task branch and document the branch/worktree divergence. | Focused pytest plus `make verify` |
| Medium | Medium | The extracted-review work-experience editor lost its title-and-bullet block formatting when mandatory profile fields were added on the task branch. | Restore review block helpers, adaptive sizing, and review-block parsing while keeping the new mandatory fields. | `tests/test_candidate_profile_ui.py`, `tests/test_cv_extraction.py` |
| Medium | Low | The repository had no durable record explaining which commits were rescued from `main` and which task-branch behaviors were intentionally preserved. | Add this run report before publish and merge steps. | File review |

## Patch Applied

- Summary: Reconciled the candidate-profile UI and extraction behavior so the task branch now keeps the Browser Use and fill-plan work, retains the new mandatory identity/address fields, and restores the previously committed `main` behavior for extracted-review ordering, work-experience block formatting, and adaptive review-field sizing.
- Rescued from `main`:
  - `97c5e5d` `Improve CV extracted review formatting`
  - `1e1f4d0` `Format CV work experience review blocks`
  - `d38ccfc` `Show extracted CV review after upload`
- Preserved from `task/0-browser-use-base`:
  - Browser Use launcher/session work
  - reviewed fill-plan workflow and evidence fields
  - job workspace review controls and related tests
- Preserved from the current task-branch candidate-profile changes:
  - separate required `first_name` and `last_name`
  - required normalized email and phone
  - required address and nationality fields
  - legacy `full_name` migration behavior
- Public API, schema, prompt, or dependency changed:
  - Candidate profile schema now explicitly stores first name, surname, street number, and nationality.
  - CV extraction prompt now combines the rescued review-format rules with the new identity/address extraction instructions.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_candidate_profile_ui.py tests/test_cv_extraction.py tests/test_schemas.py tests/test_app.py tests/test_application_fill_plan.py tests/test_job_workspace_ui.py`
- Result: Passed (`95 passed`)
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed (`208 passed`)
- Failure summary, if any: None
- CI result, if applicable: GitHub state is pending until push and merge complete.

## Follow-Up

- Stopped work: None
- Approval needed: None for commit, push, merge, or GitHub issue creation because publish work was explicitly requested.
- Next smallest useful patches:
  - Add a lightweight branch/worktree provenance checklist for future repository publish work.
  - Add a small automation check that flags local task branches when `main` contains newer commits touching the same candidate-profile files.
