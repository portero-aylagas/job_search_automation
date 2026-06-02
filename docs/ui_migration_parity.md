# Streamlit to React/FastAPI Parity Checklist

This checklist records the current Streamlit workflow before implementation and
is the migration contract for the first React/FastAPI version. The target is UI
platform parity, not product redesign.

## Top Navigation

| Streamlit page | React equivalent | Parity notes |
| --- | --- | --- |
| Candidate Profile | Candidate Profile tab | Top-level tab preserved. |
| Job Intake | Job Intake tab | Top-level tab preserved. |
| Jobs | Jobs tab | Top-level tab preserved. |
| Tracker | Tracker tab | Top-level tab preserved. |
| Agent Karen | Agent Karen tab plus persistent side panel | Agent Karen tab remains as a dashboard; chat is app-level and persistent. |

## Candidate Profile

| Streamlit section/action | React/FastAPI equivalent | Parity notes |
| --- | --- | --- |
| 1. CV Upload | CV upload section | Mandatory CV upload is preserved. |
| Parse CV with AI | `Parse CV with AI` button calling API extraction endpoint | Label and AI gate preserved. |
| 2. Optional documents | Optional document upload groups | Reference, certificate, and other document uploads preserved. |
| Parse optional documents with AI | `Parse optional documents with AI` button calling API extraction endpoint | Label and AI gate preserved. |
| 3. Extracted data review | Structured editable CV review form | Identity and professional data fields preserved. |
| Save CV review changes | `Save CV review changes` local review action | Label preserved. |
| 4. Optional job-search preferences | Structured editable preferences form | Target roles, locations, remote preference, employment type, career level, availability, salary range, and EU work authorization preserved. |
| Save manual preferences | `Save manual preferences` local review action | Label preserved. |

## Job Intake

| Streamlit section/action | React/FastAPI equivalent | Parity notes |
| --- | --- | --- |
| Initial URL-first screen | URL input only until extraction | Review fields remain hidden before extraction. |
| Job URL | Job URL input | Label preserved. |
| Extract application data with AI | `Extract application data with AI` button calling API extraction endpoint | Label and AI gate preserved. |
| Review Extracted Data | Structured review form after extraction | Fixed fields and dynamic extracted fields are editable as normal fields. |
| Title, Company, Location, Remote Policy | Text inputs | Field coverage preserved. |
| Apply URL, Salary, Posted Date, Source Job ID | Text inputs | Field coverage preserved. |
| Role Summary, Requirements, Responsibilities, Nice-to-have Skills | Text areas | Field coverage preserved. |
| Additional Extracted Details | Normal editable dynamic fields | No raw JSON editor. |
| Add To Application Workflow | Save reviewed job API action | Existing Streamlit label preserved. |

## Jobs

| Streamlit section/action | React/FastAPI equivalent | Parity notes |
| --- | --- | --- |
| Job selector | Job select control | Company/title labels preserved. |
| Job Snapshot | Job snapshot panel | Location, remote policy, salary, posted date, source job ID, source URL, apply URL, role summary, role details, advanced details preserved. |
| Application Requirements | Requirements panel | Generation, refresh, structured review, evidence, and review status preserved. |
| Discover requirements from apply URL with AI | Same button label calling API discovery endpoint | Label and AI gate preserved. |
| Refresh requirements from apply URL with AI | Same button label calling API discovery endpoint | Label and AI gate preserved. |
| Application requirements review form | Structured editable review form | Job-preserving checkbox, confidence, blocked reason, requirements, fields, questions, gates, deadlines, fallback, and missing/uncertain fields preserved. |
| Save requirements review | Same button label calling API review endpoint | Label preserved. |
| Application Package | Package panel | Generation, regeneration, artifact review, traceability metadata, and cover-letter export preserved. |
| Generate application package with AI | Same button label calling API generation endpoint | Label and AI gate preserved. |
| Regenerate application package with AI | Same button label calling API generation endpoint | Label and AI gate preserved. |
| Artifact text review | Text areas per artifact | Package review remains artifact text review, not raw JSON. |
| Save package review | Same button label calling API review endpoint | Label preserved. |
| Export cover letter PDF | Same button label calling API export endpoint | Label preserved. |
| Application Fill Plan | Fill plan panel | Generation, refresh, structured review, uploads, required fields, optional fields, field-type controls preserved where possible. |
| Generate fill plan with AI | Same button label calling API generation endpoint | Label and AI gate preserved. |
| Refresh fill plan with AI | Same button label calling API generation endpoint | Label and AI gate preserved. |
| Fill plan review | Structured/editable fields | Checkboxes, select/radio, multi-select, text inputs, and upload-path review are preserved. |
| Save fill plan review | Same button label calling API review endpoint | Label preserved. |
| Apply to position | Apply panel | Browser Use launch remains explicit and gated. |
| Apply to job with AI | Same button label calling API launch endpoint | Label and AI gate preserved. |
| Browser process controls | Collapsed secondary controls | Controls do not dominate the apply panel. |
| Stop Browser Use Session | Same button label calling API stop endpoint | Label preserved. |
| Kill All Browser Use Processes | Same button label calling API kill endpoint | Label preserved. |

## Tracker

| Streamlit section/action | React/FastAPI equivalent | Parity notes |
| --- | --- | --- |
| Tracker table | Tracker table | Same tracker record fields shown from JSON data. |

## Agent Karen

| Streamlit section/action | React/FastAPI equivalent | Parity notes |
| --- | --- | --- |
| Karen portrait/title | Agent Karen dashboard header and side-panel header | Top-level page preserved; chat remains visible across pages. |
| Job selector | Persistent side-panel job select control | Same selected-job concept without duplicating chat controls in the dashboard. |
| Workflow status metrics | Dashboard status summary | Job, gate, action count, blockers, errors, and timeline preserved. |
| Next Actions | Static guidance | Review-gated actions point users to Jobs page panels rather than executing hidden workflow actions. |
| Chat transcript | Persistent side-panel transcript | Persisted Karen messages rendered across top-level pages. |
| Ask Karen | Persistent side-panel chat input | Chat turn routed through existing Karen graph. |

## Intentional Deviations

- Karen chat intentionally moved from the `Agent Karen` tab into a persistent
  app-level side panel. The tab remains as a status/dashboard view.

## Pending Follow-Up Tasks

- #100: Add a one-command local startup path for the FastAPI backend and Vite
  frontend.
- #100: Decide and implement the production hosting path for the React build:
  FastAPI-served static assets, separate frontend hosting, or another explicit
  deployment shape.
