# Test Strategy

This repository tests the active controlled known-job application workflow:

```text
candidate profile + reviewed job position -> reviewed application package
```

Tests should protect human review gates, persisted JSON contracts, and the
thin React/FastAPI workflow surface. They should not turn optional external
systems into required local verification dependencies.

## Test Pyramid

### Python Domain And Workflow Tests

The base of the test suite is Python tests under `tests/`. These tests should
cover deterministic workflow behavior:

- Pydantic schema normalization and validation
- JSON storage paths and runtime/template loading rules
- candidate profile, job intake, requirements, package, fill-plan, and apply
  blockers
- prompt rendering where prompt templates are the behavior under test
- provider-boundary contracts such as OpenAI calls staying behind
  `src/llm_client.py`

These tests should use direct function calls and small temporary runtime
directories. They should not require a live API server, live OpenAI credentials,
Browser Use, or external websites.

### FastAPI Contract Tests

`tests/test_api.py` covers the adapter layer between React and the Python
workflow modules. These tests should verify:

- stable response shapes for route families
- request validation and error status codes
- persistence side effects for reviewed state
- review-gate behavior before package generation, fill-plan generation, and
  apply assistance

Expensive or external behavior must be injected or monkeypatched at the
`src.api` boundary. Examples include CV parsing, requirements discovery,
package generation, fill-plan generation, Karen chat processing, and Browser
Use launch.

### React Component Tests

Vitest tests in `frontend/src/` cover frontend workflow behavior in jsdom:

- rendering API-loaded state
- editable review fields
- save and error handling
- job workspace blockers and enabled actions
- Karen side-panel chat request shape and reload behavior
- `apiRequest` JSON success and error handling

These tests mock `fetch` per test. They should not start FastAPI or Vite, and
they should not depend on real network access.

### Browser Smoke Tests

Playwright tests in `e2e/` are the top of the pyramid. They should remain
small mocked acceptance tests that prove the browser can exercise core flows:

- top-level navigation renders all product pages
- Job Intake works from URL entry through reviewed save
- Jobs workspace shows human review gates and blocks Apply until prerequisites
  are mocked as reviewed

Playwright tests mock `http://127.0.0.1:8001/api/**` and start only the Vite
frontend. They must not require a live FastAPI process, OpenAI key, Browser Use
session, real job site, or internet access.

## What Not To Test

Avoid tests that fail because prose or repository metadata changed rather than
product behavior changed. In particular, do not add tests for:

- exact README wording
- generic file-existence checklists
- dependency bound formatting
- delivery-status prose in planning docs
- broad source scans that duplicate a more focused architecture contract
- long exact prompt substrings when a structured payload can be parsed instead

Policy-focused documentation tests are allowed when they prevent a recurring
source-of-truth regression. For example, it is acceptable to test that the
public README does not include repo-local Conda setup instructions, because
`AGENTS.md` owns that agent workflow while the README stays portable for normal
users.

For Browser Use launcher prompts, prefer parsing the embedded fill-plan JSON and
asserting the reviewed payload structure plus core safety invariants.

## Mocking Policy

Mock external or nondeterministic systems at the narrowest useful boundary:

- AI extraction and generation: patch the relevant `src.api` callable or module
  helper under test.
- Browser Use launch: patch process launch helpers or the API launcher call.
- Frontend browser tests: mock `/api/**` network responses.
- Local storage: use `tmp_path` and the normal JSON persistence helpers.

Do not mock simple deterministic domain logic just to make assertions shorter.

## Verification

Use an activated Python environment with `requirements.txt` installed for
Python verification. The README documents `.venv` as the default local setup,
but Conda or another environment manager works too.

```bash
make verify
```

`make verify` runs:

1. Ruff
2. Python compile checks
3. Pytest
4. TypeScript typecheck
5. Vitest component tests
6. Vite production build
7. Playwright smoke tests

Python dependencies live in `requirements.txt`. Frontend and browser test
dependencies live in `package.json` and `package-lock.json`.

## Reports And Artifacts

Local verification writes generated reports that are useful for inspection but
should not be committed:

- `reports/pytest.xml`
- `reports/vitest.xml`
- `playwright-report/`
- `test-results/`

The Playwright HTML report can be opened locally after a run with:

```bash
npx playwright show-report
```

GitHub Actions uploads these paths as the `test-reports` artifact for each
verification run. Use those CI artifacts for screenshots, traces, videos, and
machine-readable test reports.

For pushes to `main`, GitHub Actions also publishes the latest Playwright HTML
report to GitHub Pages through the `publish-playwright-report` job. The direct
browser URL appears in that job's GitHub Actions summary. Pull requests keep
the downloadable artifact only and do not publish Pages reports.
