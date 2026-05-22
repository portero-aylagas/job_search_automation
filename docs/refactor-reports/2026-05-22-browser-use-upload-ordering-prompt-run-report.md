# 2026-05-22 Browser Use Upload Ordering Prompt Run Report

## Goal

Fix the mandatory-checkbox regression in Browser Use apply assistance while
preserving the working multi-file upload handoff.

## Scope

- In scope:
  - Browser Use task text in `src/browser_use_launcher.py`
  - focused prompt-contract assertions in `tests/test_browser_use_launcher.py`
  - documentation of the final Browser Use execution order
- Out of scope:
  - Browser Use controller/tool wrapper changes
  - schema changes
  - upload generation changes
  - navigation, tab recovery, or submission behavior

## Implementation Notes

- Kept the reviewed payload sections unchanged:
  `field_values_before_upload`, `mandatory_checkbox_fields`,
  `intentionally_blank_fields`, `intentionally_untouched_checkbox_fields`, and
  `upload_files_last`.
- Simplified the action order to fill fields first, process mandatory
  checkboxes exactly once, and upload files last.
- Removed the separate pre-upload live-value and checkbox verification pass
  that could cause a checked mandatory checkbox to be clicked a second time.
- Preserved checkbox safety: inspect the live state first, click only if
  unchecked, then mark the checkbox complete and never click it again.
- Preserved upload safety: upload only after reviewed fields and mandatory
  checkboxes are complete or explicitly failed, and upload each listed file path
  at most once.

Relevant history:

- `b6b0338` / `d85e7a1`: multi-file upload handoff and upload constraints.
- `4f32af1`: mandatory checkbox confirmation.
- `a97cff8`: separate pre-upload verification step that likely caused the
  second checkbox click.
- `fc8cb98`: useful action-intent split that this change keeps while reducing
  prompt complexity.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" pytest tests/test_browser_use_launcher.py`
- Result: Passed (`26 passed`)
- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed (`265 passed`)
