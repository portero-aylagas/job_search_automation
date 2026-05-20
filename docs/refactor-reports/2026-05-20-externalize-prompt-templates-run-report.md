# Safe Improvement Run Report

## Metadata

- Date: 2026-05-20
- Mode: Local Safe Refactor Mode
- Repository: `job_search_automation`
- Branch: `task/extract-llm-client`
- Commit before: `7e44620`
- Commit after: pending commit for prompt-template externalization
- Agent: Codex GPT-5
- User approval: Safe refactor and publish work was explicitly requested.

## Scope

- User request: Move inline AI prompts into YAML prompt templates, keep the refactor documented, and publish it through the repository workflow.
- Files inspected: `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `README.md`, `requirements.txt`, `src/cv_extraction.py`, `src/llm_job_extraction.py`, `src/application_requirements.py`, `src/application_package.py`, `src/apply_url_resolution.py`, `tests/test_project_artifacts.py`
- Files changed: `README.md`, `requirements.txt`, `src/cv_extraction.py`, `src/llm_job_extraction.py`, `src/application_requirements.py`, `src/application_package.py`, `src/apply_url_resolution.py`, `src/prompt_templates.py`, `src/prompts.yaml`, `tests/test_project_artifacts.py`
- Out of scope: Prompt redesign, provider changes, UI changes, schema changes, CI changes

## Characterization

- Existing tests or checks used: focused prompt-backed workflow tests plus full-repo `make verify`
- New characterization added: A project-artifact test now checks that prompt templates exist and render from YAML.
- Manual checklist, if used:
  - Confirm all inline prompt strings were replaced by named templates
  - Confirm prompt loading stays local to one helper module
  - Confirm full local verification passes after adding `PyYAML`

## Findings And Backlog

| Priority | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- |
| Medium | Medium | Prompt text remained embedded in workflow modules, which made prompt review and iteration harder. | Externalize prompt text to `src/prompts.yaml` and load named templates through one helper module. | `PATH="$PWD/.conda/bin:$PATH" make verify` |
| Low | Low | The README did not describe the new prompt-template location. | Add a short README note about `src/prompts.yaml`, `src/prompt_templates.py`, and `src/llm_client.py`. | File review |

## Patch Applied

- Summary: Prompt strings were moved from AI workflow modules into `src/prompts.yaml`, a small YAML-backed loader was added in `src/prompt_templates.py`, the prompt-backed call sites were updated to render named templates, and the README plus artifact tests were updated accordingly.
- Why this is one patch: The patch has one purpose, which is making prompt storage explicit and reviewable without changing the surrounding workflow contracts.
- Behavior changed: No intended workflow behavior change; prompt text moved from inline Python strings to rendered YAML templates.
- Public API, schema, prompt, or dependency changed: Prompt storage changed and `PyYAML` was added as a runtime dependency. No persisted schema changed.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed
- Failure summary, if any: One initial `ruff` import-order issue in `src/prompt_templates.py` was fixed before the final verify run.
- CI result, if applicable: Not run before commit; GitHub PR checks are expected after push.

## Follow-Up

- Stopped work: None
- Approval needed: None for local commit/push/PR/merge work because it was explicitly requested.
- Next smallest useful patch: Add prompt-focused regression tests for one or two rendered templates per workflow module if prompt evolution becomes frequent.
