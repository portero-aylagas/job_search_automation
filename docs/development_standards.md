# Development Standards

This repository is a controlled human-in-the-loop job application workflow.
Development standards should keep runtime behavior understandable, reviewable,
and safe for local candidate data.

## Documentation Standards

Update documentation in the same change when behavior, workflow gates, storage
locations, environment variables, or verification steps change.

Use these files for their current responsibilities:

- `PROJECT_SPEC.md`: product behavior, workflow constraints, and durable scope.
- `IMPLEMENTATION_PLAN.md`: delivered status, pending work, and phase details.
- `README.md`: setup, run, verification, project structure, and current user
  workflows.
- `AGENTS.md`: repository-specific agent and development instructions.
- `docs/refactor-reports/`: durable reports for safe-improvement runs,
  verification failures, medium/high-risk patches, and full automation work.

Keep documentation factual. Do not describe a feature as delivered until the
code, tests, and normal verification support that status.

## Repository Hygiene Standards

Do not commit local candidate data, uploaded documents, runtime job state,
browser session artifacts, secrets, virtual environments, generated caches, or
derived application exports.

The tracked sample files under `data/` are bootstrap fixtures. Runtime state
belongs under ignored paths such as `data/runtime/`, local profile output belongs
in `data/candidate_profile.json`, and generated Markdown exports belong under
`outputs/`.

Before publishing implementation work, run:

```bash
PATH="$PWD/.conda/bin:$PATH" make verify
```

Use `make clean-local-state` only when you intentionally want to remove ignored
runtime data and derived exports from the working tree.

## Documentation Review Checklist

For each change, check whether it affects:

- visible workflow behavior
- persisted JSON shape or storage location
- generated artifacts or exports
- AI provider configuration, prompt ownership, or live-service requirements
- local setup, Browser Use setup, or verification commands
- delivered/pending status in the implementation plan

If a change touches one of those areas, update the relevant documentation and
add or adjust a focused test when the drift is easy to check automatically.

## Skill Boundary

`skills/safe_project_improvement_system/` is a development/support skill. It is
not part of the runtime application unless runtime code explicitly imports or
executes it.

Use that skill for safe review, refactoring, verification setup, and quality
improvements. Normal feature work should follow `AGENTS.md`, `PROJECT_SPEC.md`,
and `IMPLEMENTATION_PLAN.md` without presenting development-support skills as
application functionality.
