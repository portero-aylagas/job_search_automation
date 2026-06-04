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
tracks source-grounding checks for hallucinated or unsupported extracted facts,
including rejected apply-link candidates and other unsupported URLs.

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

The application URL is a workflow gate. Email-only contact paths, contact
people, and the original job-offer URL are useful facts to preserve, but they
are not valid `apply_url` values. Issue #35 tracks stricter reachability and
job-identity validation before downstream workflow steps continue.

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

- normalized job JSON in `data/runtime/jobs/<job_id>/normalized_job.json`
- shared job index in `data/runtime/jobs.json`
- application page snapshot JSON in `data/runtime/jobs/<job_id>/application_page_snapshot.json`
- application requirements JSON in `data/runtime/jobs/<job_id>/application_requirements.json`
- application package JSON in `data/runtime/jobs/<job_id>/application_package.json`
- application fill plan JSON in `data/runtime/jobs/<job_id>/application_fill_plan.json`
- generated Markdown exports in `outputs/<job_id>/`

Runtime files under `data/runtime/` are the source of truth. Markdown files in
`outputs/` are derived from structured JSON. Test, mock, example, and
template-style data belong in `tests/fixtures/`.

`normalized_job.json` describes the job offer only. The working apply-page
requirements flow first stores `application_page_snapshot.json` from a read-only
inspection of `apply_url`, then creates `application_requirements.json` from
that snapshot. The requirements artifact captures required documents,
motivation letter requirements, screening questions, form fields, and any
missing information that needs human review.

`data/runtime/jobs.json` is the canonical shared index for the Tracker and Jobs
views. The tracked `data/jobs.json` file and any `data/jobs/<job_id>/...`
artifacts are templates or bootstrap fallback data, not the primary runtime
write location. Legacy `tracker.json` files may be read as fallback only when
the canonical jobs index is missing.

The core pipeline remains:

```text
candidate profile + job position -> validated application package
```

## Browser Automation Capability Summary

The researched options can all support browser-based job application
assistance, but they differ in control level, reliability, and implementation
effort.

### Browser Use

Browser Use is an agent-oriented browser automation framework. It is the
closest option to an OpenClaw-like experience: the application can give the
agent a high-level task such as opening an apply URL, filling the form,
uploading documents, and stopping before final submission.

**Strengths**

- Fastest option for prototyping.
- Python-friendly.
- Can reason through multi-step pages.
- Can provide task-level feedback such as `ready_for_user_submit` or
  `blocked_login_required`.

**Weaknesses**

- Less deterministic than direct Playwright control.
- Needs strong guardrails to prevent unwanted clicks.
- Harder to audit precisely unless wrapped with structured status reporting.

### Playwright + Browserbase

Playwright provides deterministic browser control. Browserbase provides
remote/cloud browser infrastructure. Together, they are the strongest
production-oriented option if the app should run browser sessions without
relying on the user's local browser.

**Strengths**

- High control over clicks, typing, uploads, waits, screenshots, and traces.
- Suitable for structured fill plans.
- Easier to enforce a hard submit guard.
- Browserbase can host remote browser sessions.

**Weaknesses**

- Requires building the field inspection, field mapping, fill execution, and
  audit logic.
- Browserbase adds an external service dependency and cost.
- Not an agent by itself; reasoning must be implemented separately.

### OpenAI Computer Use

Computer Use is a visual UI-control option where the model operates from
screenshots and returns actions such as click, type, scroll, or wait. It is
useful when DOM-based automation fails.

**Strengths**

- Can handle visually complex or poorly structured pages.
- Useful fallback for custom UI components.
- Can reason from screenshots rather than HTML structure.

**Weaknesses**

- Still needs a browser harness.
- Slower, less deterministic, and harder to test.
- Higher risk of misclicks.
- Should not be the primary engine for normal forms.

### OpenClaw-Style Browser Layer

Instead of using OpenClaw as a runtime dependency, the useful pattern can be
reproduced inside the project: browser snapshots, stable element references,
bounded actions, repeated wait/snapshot loops, audit logs, and a deterministic
submit guard.

**Strengths**

- Best long-term architecture for this project.
- Python-only if implemented with Playwright.
- Matches the existing human-in-the-loop workflow.
- Allows structured run results and auditability.
- Can later support Browserbase or Computer Use as backends/fallbacks.

**Weaknesses**

- More engineering work.
- Requires implementing browser session handling, snapshots, refs, uploads,
  waits, and guards.

## Recommended Direction

Use a layered approach:

1. **Browser Use** for fast benchmarking on real application pages.
2. **Own Playwright-based OpenClaw-style browser layer** as the production
   core.
3. **Browserbase** as a remote browser backend once local Playwright works.
4. **OpenAI Computer Use** only as a fallback for pages where DOM/ref
   automation fails.

Every browser run should return a structured result:

```json
{
  "status": "ready_for_user_submit",
  "message": "Application page prepared. Review it and click Submit manually.",
  "filled_fields": ["First name", "Email", "Phone", "CV"],
  "blocked_fields": [],
  "uploaded_files": ["CV"],
  "screenshot_path": "data/runtime/jobs/job-123/final_review.png"
}
```
