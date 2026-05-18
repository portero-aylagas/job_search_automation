# Research Foundation

## Baseline Intake

The sprint baseline is manual-first job intake:

- pasted job description
- pasted job URL for source provenance
- manual fallback fields for title, company, location, remote policy, apply URL, and description

URL extraction and public job discovery are useful add-ons, but they should not block the core workflow.

## Discovery Approach

Preferred discovery path for this sprint:

- start with manual job intake
- add one lightweight discovery option only after the core workflow works
- evaluate API, MCP, or web search based on reliability and setup cost

Initial priority:

1. manual intake
2. structured import or pasted job text
3. public web/API/MCP discovery as an add-on

## Costs, Limits, and Authentication

The early local workflow must run without live credentials.

Expected optional credentials:

- `OPENAI_API_KEY` for later application-package generation and optional web search
- provider-specific credentials only if a job-search API or MCP path is selected

Costs and rate limits should be documented when a live provider is added. Until then, tests should use sample data or fake clients.

## Output Structure

Core outputs:

- normalized job JSON in `data/jobs/`
- match analysis JSON in `data/jobs/`
- application package JSON in `data/applications/`
- generated Markdown artifacts in `outputs/<job_id>/`
- tracker state in `data/tracker.json`

The core pipeline remains:

```text
candidate profile + job position -> validated application package
```
