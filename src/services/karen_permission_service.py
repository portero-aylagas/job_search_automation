"""Per-job Karen permission grants persisted on agent sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.agent_chat import get_or_create_agent_session
from src.paths import agent_session_path
from src.schemas import AgentJobPermissionGrant, AgentSession
from src.storage import save_model


def grant_job_session_permission(
    base_dir: Path | str,
    *,
    session_id: str,
    job_id: str,
    allow_app_mutations: bool = True,
    allow_browser_launch: bool = False,
) -> AgentSession:
    """Grant Karen scoped permissions for one job in one session."""

    session = get_or_create_agent_session(base_dir, session_id, selected_job_id=job_id)
    existing = session.job_permissions.get(job_id)
    now = datetime.now(timezone.utc).isoformat()
    grant = AgentJobPermissionGrant(
        allow_app_mutations=allow_app_mutations,
        allow_browser_launch=allow_browser_launch,
        granted_at=existing.granted_at if existing is not None else now,
        updated_at=now,
    )
    session.job_permissions[job_id] = grant
    session.updated_at = now
    save_model(agent_session_path(base_dir, session.session_id), session)
    return session


def revoke_job_session_permission(
    base_dir: Path | str,
    *,
    session_id: str,
    job_id: str,
) -> AgentSession:
    """Remove Karen's scoped permissions for one job in one session."""

    session = get_or_create_agent_session(base_dir, session_id, selected_job_id=job_id)
    session.job_permissions.pop(job_id, None)
    session.updated_at = datetime.now(timezone.utc).isoformat()
    save_model(agent_session_path(base_dir, session.session_id), session)
    return session


def inspect_job_session_permission(
    base_dir: Path | str,
    *,
    session_id: str,
    job_id: str,
) -> AgentJobPermissionGrant:
    """Return the current grant for one job, or an empty grant if absent."""

    session = get_or_create_agent_session(base_dir, session_id, selected_job_id=job_id)
    return session.job_permissions.get(job_id, AgentJobPermissionGrant())


def job_permission_allows(
    session: AgentSession,
    *,
    job_id: str | None,
    app_mutation: bool = False,
    browser_launch: bool = False,
) -> bool:
    """Return whether a session grant covers the requested job-scoped action."""

    if not job_id:
        return False
    grant = session.job_permissions.get(job_id)
    if grant is None:
        return False
    if app_mutation and not grant.allow_app_mutations:
        return False
    if browser_launch and not grant.allow_browser_launch:
        return False
    return True
