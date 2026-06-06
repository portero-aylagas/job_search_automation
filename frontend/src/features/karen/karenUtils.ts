import { progressStatus } from "../../app/workflowRefresh";
import type { ApiRecord } from "../../shared/types";
import { titleCase } from "../../shared/utils/format";

export const karenPanelWidthKey = "karenPanelWidth";
export const karenPanelWidthMin = 320;
export const karenPanelWidthMax = 560;
export const karenPanelWidthDefault = 380;

export function readKarenPanelWidth() {
  const savedWidth = Number(localStorage.getItem(karenPanelWidthKey));
  return clampNumber(savedWidth || karenPanelWidthDefault, karenPanelWidthMin, karenPanelWidthMax);
}

export function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function isActiveKarenRunStatus(status: string) {
  return ["queued", "running"].includes(status);
}

export function latestWorkflowRunId(events: ApiRecord[]) {
  const event = [...events]
    .reverse()
    .find((item) => item.run_id || item.details?.workflow_run_id);
  return event?.run_id || event?.details?.workflow_run_id || "";
}

function shouldRefreshForKarenEvent(event: ApiRecord) {
  return (
    event.action &&
    (!event.event_type || event.event_type === "workflow_action") &&
    progressStatus(event) === "completed" &&
    eventRefreshScopes(event).length > 0
  );
}

function eventRefreshScopes(event: ApiRecord) {
  const value = event.refresh_scopes || event.metadata?.refresh_scopes || event.details?.refresh_scopes || [];
  return Array.isArray(value) ? uniqueStrings(value.map(String)) : [];
}

function karenRefreshEventKey(event: ApiRecord) {
  const runId = event.run_id || event.details?.workflow_run_id || "run";
  const stepIndex = event.details?.step_index ?? "";
  const status = progressStatus(event);
  const timestamp = event.timestamp || event.created_at || "";
  return `${runId}:${stepIndex}:${event.action}:${status}:${timestamp}`;
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function hasAnyRefreshScope(scopes: string[] = [], targets: string[]) {
  return targets.some((target) => scopes.includes(target));
}

export function isBlockedKarenEvent(event: ApiRecord) {
  if (event.status) {
    return ["blocked", "needs_input", "refused", "error"].includes(String(event.status));
  }
  return !["understood", "started", "done", "executed"].includes(String(event.result || ""));
}

export function eventActionLabel(event: ApiRecord, actionLabels: ApiRecord = {}) {
  return event.label || event.details?.action_label || actionLabels[event.action] || titleCase(String(event.action || ""));
}

export function formatKarenIntent(event: ApiRecord) {
  const goal = titleCase(String(event.details?.goal || "workflow request"));
  const mode = event.details?.execution_mode ? `, ${titleCase(String(event.details.execution_mode))}` : "";
  return `${goal}${mode}`;
}

export function formatKarenBlockedEvent(event: ApiRecord, actionLabels: ApiRecord = {}) {
  const blockers = Array.isArray(event.blockers) ? event.blockers.filter(Boolean) : [];
  const reason = blockers.length
    ? blockers.join("; ")
    : event.message || event.details?.error || event.details?.planner_message || titleCase(String(event.result || "blocked"));
  const route = event.route_hint ? ` Go to: ${event.route_hint}.` : "";
  return `${eventActionLabel(event, actionLabels)}: ${reason}.${route}`.replace(/\.\./g, ".");
}

export function karenProgressSteps(events: ApiRecord[], actionLabels: ApiRecord = {}) {
  const steps: ApiRecord[] = [];
  const stepIndexes = new Map<string, number>();
  const progressEvents = events.filter((event) => (
    event.action &&
    (!event.event_type || event.event_type === "workflow_action") &&
    !["karen_workflow_intent", "karen_workflow_run"].includes(String(event.action))
  ));

  for (const event of progressEvents) {
    const key = karenStepKey(event, steps.length);
    const status = progressStatus(event);
    const existingIndex = stepIndexes.get(key);
    const step = {
      action: event.action,
      label: eventActionLabel(event, actionLabels),
      status,
      order: Number(event.details?.step_index ?? steps.length)
    };
    if (existingIndex === undefined) {
      stepIndexes.set(key, steps.length);
      steps.push(step);
    } else {
      steps[existingIndex] = { ...steps[existingIndex], ...step };
    }
  }

  return steps.slice(0, 8);
}

function karenStepKey(event: ApiRecord, fallbackIndex: number) {
  const runId = event.run_id || event.details?.workflow_run_id || "run";
  const stepIndex = event.details?.step_index ?? fallbackIndex;
  return `${runId}:${stepIndex}:${event.action}`;
}

export function progressStepSymbol(status: string) {
  if (status === "completed") return "✓";
  if (status === "running") return "▶";
  if (["blocked", "needs_input", "refused", "error"].includes(status)) return "!";
  return "○";
}


export function karenActionTarget(actionName: string) {
  const normalized = actionName.toLowerCase();
  if (normalized.includes("profile")) return { page: "Candidate Profile", sectionId: "workflow-profile" };
  if (normalized.includes("intake") || normalized.includes("job")) return { page: "Job Intake" };
  if (normalized.includes("requirement")) return { page: "Jobs", sectionId: "workflow-requirements" };
  if (normalized.includes("package") || normalized.includes("cover")) return { page: "Jobs", sectionId: "workflow-package" };
  if (normalized.includes("fill")) return { page: "Jobs", sectionId: "workflow-fill-plan" };
  if (normalized.includes("apply") || normalized.includes("browser")) return { page: "Jobs", sectionId: "workflow-apply" };
  if (normalized.includes("track")) return { page: "Tracker" };
  return null;
}

