import type { KarenEventPayload } from "../shared/types";

export const fullWorkflowRefreshScopes = [
  "job_workspace",
  "jobs_index",
  "tracker",
  "candidate_profile",
  "agent_context"
];

export function workflowPageHandlesRefresh(pageName: string) {
  return ["Candidate Profile", "Jobs", "Tracker"].includes(pageName);
}

export function shouldRefreshForKarenEvent(event: KarenEventPayload) {
  return (
    event.action &&
    (!event.event_type || event.event_type === "workflow_action") &&
    progressStatus(event) === "completed" &&
    eventRefreshScopes(event).length > 0
  );
}

export function eventRefreshScopes(event: KarenEventPayload) {
  const value = event.refresh_scopes || event.metadata?.refresh_scopes || event.details?.refresh_scopes || [];
  return Array.isArray(value) ? uniqueStrings(value.map(String)) : [];
}

export function karenRefreshEventKey(event: KarenEventPayload) {
  const runId = event.run_id || event.details?.workflow_run_id || "run";
  const stepIndex = event.details?.step_index ?? "";
  const status = progressStatus(event);
  const timestamp = event.timestamp || event.created_at || "";
  return `${runId}:${stepIndex}:${event.action}:${status}:${timestamp}`;
}

export function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

export function hasAnyRefreshScope(scopes: string[] = [], targets: string[]) {
  return targets.some((target) => scopes.includes(target));
}

export function progressStatus(event: KarenEventPayload) {
  if (event.status) return String(event.status);
  if (event.result === "started") return "running";
  if (["done", "executed"].includes(String(event.result || ""))) return "completed";
  return String(event.result || "blocked");
}
