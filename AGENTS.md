# Project Agent Instructions

This repository contains a Python application for a controlled human-in-the-loop job application workflow.

The core feature is:

```text
candidate profile + job position -> validated application package
```

## Priority Order

When working in this repository, follow this order:

1. `AGENTS.md`
2. `PROJECT_SPEC.md`
3. `IMPLEMENTATION_PLAN.md`
4. Existing code and tests
5. Task-specific user instructions

Do not silently expand scope beyond the current requested phase.

## Normal Development

For normal feature implementation, follow the project specification and implementation plan.

Keep changes small, readable, and verifiable.

Prefer simple working code over abstract architecture.

Use JSON file storage first unless explicitly asked otherwise.

## Skills Boundary

Use skills only when they are directly relevant to the task.

Skills documented in this repository fall into two categories:

- `runtime/project skills`: skills that define or support the application's runtime behavior
- `development/support skills`: skills used during implementation to improve code quality, testing, prompts, documentation, and maintainability

Do not describe a development/support skill as part of the runtime application unless the code explicitly integrates it.

## Safe Project Improvement System

The folder `skills/safe_project_improvement_system/` is available for safe code review, incremental refactoring, verification setup, and quality improvements.

Treat it as a `development/support skill`, not as a runtime component of this application.

Use `skills/safe_project_improvement_system/` only when explicitly asked to review, refactor, audit, add verification, or improve project quality safely.

When asked to improve the repository safely, read:

```text
skills/safe_project_improvement_system/SKILL.md
```

Then load only the references needed for the current task.

Do not use the safe project improvement system for normal feature implementation unless explicitly requested.
