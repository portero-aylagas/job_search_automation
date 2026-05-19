# Research Foundation

## Baseline Intake

The sprint baseline is URL-only LLM-assisted extraction with manual review fallback:

- first-screen Job URL input
- LLM or agent extraction into a review form
- required visible review fields: title, company, source URL
- optional extracted role fields such as location, remote policy, description, requirements, salary, posted date, and apply URL
- hidden internal retrieval mode and generated app job ID
- optional external/source job ID when the source provides one

Manual review remains mandatory because extraction can be incomplete. Pasted job
text is a fallback when a URL cannot be read, not the primary intake baseline.
Public job discovery is a useful add-on, but it should not block the core
workflow.

AI extraction must be treated as assisted drafting, not ground truth. Issue #36
tracks source-grounding checks for hallucinated or unsupported extracted facts.

## Discovery Approach

Preferred discovery path for this sprint:

- start with URL-only LLM-assisted extraction and manual review fallback
- add one lightweight discovery option only after the core workflow works
- evaluate API, MCP, or web search based on reliability and setup cost

Initial priority:

1. URL-only LLM-assisted extraction with manual review fallback
2. structured import or pasted job text fallback
3. public web/API/MCP discovery as an add-on

The common market pattern is a public job-offer page followed by a separate
application step. The app stores the public offer in `normalized_job.json`, then
later follows or inspects `apply_url` to discover whether the application form
requires a CV, motivation letter, screening answers, portfolio links, or other
fields.

The application URL is a workflow gate. Email-only contact paths and contact
people are useful dynamic details, but they are not a valid `apply_url`. Issue
#35 tracks stricter reachability validation before downstream workflow steps.

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
job URL / reviewed fallback text / API result / MCP result -> normalized job listing -> tracker
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

- normalized job JSON in `data/jobs/<job_id>/normalized_job.json`
- application requirements JSON in `data/jobs/<job_id>/application_requirements.json`
- match analysis JSON in `data/jobs/<job_id>/analysis.json`
- application package JSON in `data/jobs/<job_id>/application_package.json`
- generated Markdown exports in `outputs/<job_id>/`
- tracker state in `data/tracker.json`

Runtime `data/` files are the source of truth. Markdown files in `outputs/` are
derived from structured JSON. Test, mock, example, and template-style data
belong in `tests/fixtures/`.

`normalized_job.json` describes the job offer only. `application_requirements.json`
is created later from `apply_url` and captures required documents, motivation
letter requirements, screening questions, form fields, and any missing
information that needs human review.

The core pipeline remains:

```text
candidate profile + job position -> validated application package
```
