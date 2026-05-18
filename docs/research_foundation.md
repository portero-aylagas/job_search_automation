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

## Job Discovery Decision Notes

Claude Code can be used as a development assistant inside WSL, and Claude connectors can expose
remote MCP tools such as Indeed to Claude. The Indeed MCP connector is useful for exploration because
it can search and retrieve job information through Claude, but it is not selected as the runtime
foundation for this app. It depends on the Claude connector environment, is less portable than a
normal app integration, and would make the application depend on Claude-specific tooling rather than
our own ingestion and tracking flow.

LinkedIn is also not selected as a primary source. Official LinkedIn APIs are limited for this use
case, and third-party LinkedIn APIs or MCP wrappers usually create fragility, account-risk, or
scraping-policy concerns. For a bootcamp project, that is too much risk for too little core value.

More practical job discovery candidates are public job-search APIs such as:

- Adzuna
- Jooble
- Bundesagentur fuer Arbeit / Arbeitsagentur data sources

These are better candidates because they can be called from a normal Python app, tested with fake
clients, documented with clear credentials and rate limits, and treated as optional input sources.
The core data model should stay independent of the source:

```text
manual entry / pasted text / API result / MCP result -> normalized job listing -> tracker
```

Similar job-search automation repositories tend to follow the same useful split: ingestion,
normalization, deduplication, scoring, review state, and application tracking. This project should
reuse that architecture pattern rather than tying the runtime to one provider.

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
