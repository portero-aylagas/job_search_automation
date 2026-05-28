# Safe Improvement Run Report

## Metadata

- Date: 2026-05-28
- Mode: Full Automation Mode
- Repository: `job_search_automation`
- Branch: `task/safe-review-automation-fixes`
- Commit before: `ea2a57910a61f82210bfd7186b51fe338cca9409`
- Commit after: `pending during report drafting`
- Agent: Codex GPT-5
- User approval: Explicit request to use automation mode and fix all review findings

## Scope

- User request: Apply all actionable findings from the external safe-project-improvement-system review, then verify and publish the result.
- Audit families and areas selected:
  - `Engineering Audits`: `Security And Secrets`, `Data And JSON Validation`
  - `AI System Audits`: `Workflow Automation`, `Cost And Usage`
- Audit families and areas skipped:
  - `Engineering Audits`: `General Software Architecture`, `Function Responsibility`, `Error Handling`, `Testability`, `Documentation And Reviewer Evidence`, `Repository Hygiene`
  - `AI System Audits`: `AI Software Architecture`, `Prompt Quality`, `Dynamic Prompting`, `Structured Output`, `LLM/API Integration`
- Scope selection reason: The selected areas were the only ones with material findings in review mode, and the patch stays constrained to those workflow-safety issues.
- Files inspected:
  - `src/application_fill_plan.py`
  - `src/browser_use_launcher.py`
  - `src/browser_use_visible_runner.py`
  - `src/cv_extraction.py`
  - `tests/test_application_fill_plan.py`
  - `tests/test_browser_use_launcher.py`
  - `tests/test_cv_extraction.py`
- Files changed:
  - `src/application_fill_plan.py`
  - `src/browser_use_launcher.py`
  - `src/browser_use_visible_runner.py`
  - `src/cv_extraction.py`
  - `tests/test_application_fill_plan.py`
  - `tests/test_browser_use_launcher.py`
  - `tests/test_cv_extraction.py`
  - `docs/refactor-reports/2026-05-28-browser-use-safety-automation-run-report.md`
- Out of scope:
  - Prompt rewrites
  - Apply-page extraction behavior
  - UI redesign
  - New GitHub Actions or hook changes

## Characterization

- Existing tests or checks used:
  - `tests/test_application_fill_plan.py`
  - `tests/test_browser_use_launcher.py`
  - `tests/test_cv_extraction.py`
  - repository-wide `make verify`
- New characterization added:
  - Upload-path review blockers now reject unreviewed file paths before Browser Use launch.
  - Browser Use launch now blocks when another session is already active.
  - Browser Use default max-step budget now stays conservative.
  - CV uploads no longer overwrite same-second files with identical names.
- Manual checklist, if used: None

## Findings By Audit Family

```text
Engineering Audits
- Security And Secrets
  - High
    - Browser Use could be pointed at arbitrary local upload paths through edited fill-plan file paths.
- Data And JSON Validation
  - Medium
    - CV and optional-document uploads could overwrite same-second files with identical names.
- General Software Architecture
  - No material findings.
- Function Responsibility
  - No material findings.
- Error Handling
  - No material findings.
- Testability
  - No material findings.
- Documentation And Reviewer Evidence
  - No material findings.
- Repository Hygiene
  - No material findings.

AI System Audits
- Workflow Automation
  - Medium
    - Starting a new Browser Use session silently terminated an active runner instead of forcing an explicit user stop/restart decision.
- Cost And Usage
  - High
    - Browser Use defaulted to an excessive agent-step budget for a paid apply flow.
- AI Software Architecture
  - No material findings.
- Prompt Quality
  - No material findings.
- Dynamic Prompting
  - No material findings.
- Structured Output
  - No material findings.
- LLM/API Integration
  - No material findings.
```

## Backlog

| Priority | Audit Family | Audit Area | Severity | Risk | Finding | Proposed Patch | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Engineering Audits | Security And Secrets | High | Browser Use could upload unintended local files. | Fill-plan upload paths were editable free text and not constrained to reviewed sources. | Allow only reviewed upload paths from stored source metadata and require files to exist before launch. | Focused pytest plus `make verify` |
| 2 | AI System Audits | Cost And Usage | High | Paid browser-agent runs could grow too large by default. | Browser Use defaulted to `8000` max steps. | Lower the default to `120`, keep override support, and log the chosen cap. | Focused pytest plus `make verify` |
| 3 | AI System Audits | Workflow Automation | Medium | New apply launches could kill active work without explicit consent. | Launch path auto-stopped existing Browser Use sessions and stale runners. | Block launch when an active session or runner exists and require explicit stop from the UI controls. | Focused pytest plus `make verify` |
| 4 | Engineering Audits | Data And JSON Validation | Medium | Uploaded evidence files could be overwritten. | Same-second uploads with the same sanitized filename reused the same path. | Use exclusive file creation and numbered suffixes on collisions. | Focused pytest plus `make verify` |

## Patch Applied

- Summary:
  - Added reviewed-upload-path validation and file existence checks.
  - Changed Browser Use launch semantics to block on existing active runners.
  - Reduced the default Browser Use max-step budget and logged it.
  - Made upload filenames collision-resistant within the same second.
- Why this is one patch:
  - Every change addresses the reviewed automation-safety findings around Browser Use and reviewed file handling.
- Behavior changed:
  - Browser Use now refuses unreviewed or missing upload files.
  - Browser Use now refuses to start while another runner is active.
  - Browser Use agent runs now default to a much smaller step cap.
  - Repeated uploads with the same timestamped name now get unique numbered paths.
- Public API, schema, prompt, or dependency changed:
  - No public API or dependency changes.
  - Persisted fill-plan `source_metadata` is now actively enforced for upload-path review, but the stored shape did not change.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed
- Failure summary, if any:
  - One intermediate Ruff import-order failure in `src/browser_use_launcher.py`, corrected before final verification.
- CI result, if applicable:
  - GitHub Actions `Verify` run succeeded for PR #93.

## Follow-Up

- Stopped work: None
- Approval needed: None for the implemented patch
- Next smallest useful patch:
  - Surface the configured Browser Use max-step cap directly in the Jobs UI before launch so reviewers can see the budget without opening logs.
