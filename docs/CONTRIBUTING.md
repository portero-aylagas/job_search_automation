# Repository Hygiene Standards

This document describes the documentation and branch hygiene expectations for contributors.

## Branch Naming

Use the following prefixes:

| Prefix | Purpose |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Code refactoring |
| `test/` | Test additions or fixes |

Example: `docs/repo-hygiene-standards`, `feat/langgraph-workflow`

## Commit Messages

- Use the imperative mood: `Add feature`, not `Added feature`
- Keep the subject line under 72 characters
- Reference the related issue number when applicable: `Fix intake bug (#45)`

## Pull Requests

- Keep PRs focused on a single concern
- Fill in the PR description explaining **what** changed and **why**
- Link to the related issue with `Fixes #<number>` or `Closes #<number>`
- Do not merge your own PR without at least a self-review pass

## Documentation Expectations

- New features must update `README.md` if they affect the main workflow
- New scripts or modules must include a short docstring describing their purpose
- Place markdown documentation in `docs/` unless it is a root-level convention file

## Artifact Coverage

When a task produces output files (run reports, audit logs, etc.), store them in `outputs/`
and include a brief description in the relevant issue or PR so the work stays traceable.

## Keeping the Backlog Clean

- Close issues that are explicitly out of scope with a short explanation
- Use draft PRs for work in progress — avoid long-lived open PRs with no activity
- If a PR is closed without merging, open a tracking issue to keep the work visible
