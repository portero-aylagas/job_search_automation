import type { ApiRecord } from "../types";
import { titleCase } from "./format";

export function nextActionLabel(actions: string[] = [], labels: ApiRecord = {}) {
  if (!actions.length) return "None";
  return labels[actions[0]] || titleCase(actions[0]);
}

export function jobManagementNextLabel(workspace: ApiRecord, actions: string[] = [], labels: ApiRecord = {}) {
  const status = workspace.job?.status;
  if (status === "agent_assistance_attempted") return "Apply assistance attempted";
  if (["applied", "applied_manually", "applied_with_agent_assistance"].includes(status)) return "Applied";
  if (workspace.active_browser_use_session) return "Browser session active";
  return nextActionLabel(actions, labels);
}

export function profileStatus(workspace: ApiRecord) {
  const blockers = allWorkspaceBlockers(workspace).filter((item) => /profile|candidate|cv/i.test(item));
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  return { status: "complete", labelText: "Complete" };
}

export function jobStatus(workspace: ApiRecord) {
  if (!workspace.job) return { status: "missing", labelText: "Missing" };
  if (!workspace.job.apply_url) return { status: "needs-review", labelText: "Needs review" };
  return { status: "complete", labelText: "Complete" };
}

export function requirementsStatus(workspace: ApiRecord) {
  const requirements = workspace.requirements;
  if (!requirements) return { status: "missing", labelText: "Missing" };
  if (requirements.blocked_reason) return { status: "blocked", labelText: "Blocked" };
  if (requirements.confidence === "low") return { status: "low-confidence", labelText: "Low confidence" };
  if (requirements.review_status === "reviewed") return { status: "complete", labelText: "Complete" };
  return { status: "needs-review", labelText: "Needs review" };
}

export function packageStatus(workspace: ApiRecord) {
  const blockers = workspace.package_blockers || [];
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  if (!workspace.package) return { status: "missing", labelText: "Missing" };
  if (["approved", "reviewed", "complete"].includes(workspace.package.status || workspace.package.review_status)) {
    return { status: "complete", labelText: "Complete" };
  }
  return { status: "needs-review", labelText: "Needs review" };
}

export function fillPlanStatus(workspace: ApiRecord) {
  const blockers = workspace.fill_plan_generation_blockers || [];
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  if (!workspace.fill_plan) return { status: "missing", labelText: "Missing" };
  if (workspace.fill_plan.review_status === "reviewed") return { status: "complete", labelText: "Complete" };
  return { status: "needs-review", labelText: "Needs review" };
}

export function applyStatus(workspace: ApiRecord) {
  if (workspace.apply_blockers?.length) return { status: "blocked", labelText: "Blocked" };
  if (["applied", "applied_manually", "applied_with_agent_assistance"].includes(workspace.job?.status)) {
    return { status: "complete", labelText: "Complete" };
  }
  if (workspace.job?.status === "agent_assistance_attempted") return { status: "needs-review", labelText: "Agent attempted" };
  return { status: "ready", labelText: "Ready" };
}

export function reviewSummary(status?: string, confidence?: string) {
  const statusText = status ? titleCase(status) : "Needs review";
  return confidence ? `${statusText}, ${confidence} confidence` : statusText;
}

export function allWorkspaceBlockers(workspace: ApiRecord) {
  return [
    ...(workspace.package_blockers || []),
    ...(workspace.fill_plan_generation_blockers || []),
    ...(workspace.apply_blockers || [])
  ].filter(Boolean);
}

export function chooseJobId(records: ApiRecord[], preferredJobId = "", currentJobId = "") {
  if (preferredJobId && records.some((record) => record.job_id === preferredJobId)) return preferredJobId;
  if (currentJobId && records.some((record) => record.job_id === currentJobId)) return currentJobId;
  return records[0]?.job_id || "";
}


export function jobBlockerCount(record: ApiRecord, workspace: ApiRecord | null) {
  if (workspace) return allWorkspaceBlockers(workspace).length;
  return Number(record.blocker_count ?? record.blockers?.length ?? 0);
}

export function nextWorkspaceAction(record: ApiRecord, workspace: ApiRecord | null) {
  if (workspace) {
    if (!workspace.requirements) return "Discover requirements";
    if (workspace.package_blockers?.length) return "Resolve package blockers";
    if (!workspace.package) return "Generate package";
    if (workspace.fill_plan_generation_blockers?.length) return "Resolve fill plan blockers";
    if (!workspace.fill_plan) return "Generate fill plan";
    if (workspace.apply_blockers?.length) return "Resolve apply blockers";
    return "Apply with AI";
  }
  const allowedAction = nextActionLabel(record.next_allowed_actions || [], record.action_labels);
  return record.next_action || record.next_action_label || (allowedAction === "None" ? "Review workflow" : allowedAction);
}

export function trackerStatusMeta(status: string | undefined, options: ApiRecord[]) {
  const value = status || "new";
  return options.find((option) => option.value === value) || {
    value,
    label: titleCase(value),
    badge: "missing",
    user_editable: false
  };
}

export function trackerStatusLabel(status: string | undefined, options: ApiRecord[]) {
  return trackerStatusMeta(status, options).label;
}

export function trackerStatusBadge(status: string | undefined, options: ApiRecord[]) {
  return trackerStatusMeta(status, options).badge || "missing";
}

