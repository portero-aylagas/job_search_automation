# 2026-05-22 Jobs UI Polish Run Report

## Goal

Polish the Streamlit UI for Candidate Profile, Job Intake, and Jobs so the
workflow reads more cleanly and key review sections are easier to scan.

## Scope

- In scope:
  - remove low-value helper captions from Candidate Profile and Job Intake
  - simplify the Jobs workspace header area
  - render application-requirements AI details as compact bullet lists
  - wrap the main Jobs review sections in bordered containers
- Out of scope:
  - schema or storage changes
  - workflow behavior changes for requirements, package generation, or fill
    plans
  - Browser Use runtime changes

## Final Working State

- Candidate Profile now tells the user to upload CV and certifications, and no
  longer shows the CV-upload AI-provider helper caption.
- Job Intake no longer shows the extraction helper caption below the job URL.
- Jobs no longer shows the selected-job title, company caption, or top human
  review checklist before the main workspace panels.
- Jobs renders Job Snapshot, Application Requirements, Application Package, and
  Application Fill Plan in bordered containers similar to Candidate Profile.
- Optional AI-processing details for application requirements now stay in the
  same nested expanders but render as compact bullet lists instead of spaced
  line-by-line rows.

## Verification

- Command: `PATH="$PWD/.conda/bin:$PATH" make verify`
- Result: Passed (`223 passed`)
