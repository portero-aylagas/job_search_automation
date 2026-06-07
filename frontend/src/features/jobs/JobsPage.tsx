import { useEffect, useState } from "react";
import { apiRequest } from "../../api";
import { hasAnyRefreshScope } from "../../app/workflowRefresh";
import { SectionHeader, StatusBadge, StatusMessage } from "../../shared/components";
import type {
  ApiRecord,
  JobIndexRecord,
  JobsIndexPayload,
  JobWorkspacePayload,
  KarenAgentPayload,
  TrackerStatusOption
} from "../../shared/types";
import { runBusy } from "../../shared/utils/apiActions";
import { chooseJobId, jobBlockerCount, nextWorkspaceAction, trackerStatusBadge, trackerStatusLabel } from "../../shared/utils/workflow";
import {
  ApplyAssistancePanel,
  FillPlanPanel,
  JobManagement,
  JobSnapshot,
  PackagePanel,
  RequirementsPanel,
  WorkflowStepper
} from "./JobsPagePanels";

export function JobsPage({
  agent,
  onRefreshComplete,
  onNavigateToIntake,
  onSelectedJobChange,
  onWorkflowChange,
  refreshJobId,
  refreshScopes,
  refreshSignal
}: {
  agent: KarenAgentPayload | null;
  onRefreshComplete: () => void;
  onNavigateToIntake: () => void;
  onSelectedJobChange: (jobId: string) => void;
  onWorkflowChange: (jobId?: string, nextSessionId?: string) => void;
  refreshJobId: string;
  refreshScopes: string[];
  refreshSignal: number;
}) {
  const [records, setRecords] = useState<JobIndexRecord[]>([]);
  const [statusOptions, setStatusOptions] = useState<TrackerStatusOption[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [workspace, setWorkspace] = useState<JobWorkspacePayload | null>(null);
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);

  async function loadJobs(preferredJobId = selectedJobId) {
    try {
      const payload = await apiRequest<JobsIndexPayload>("/api/jobs");
      const nextRecords = payload.records || [];
      const nextJobId = chooseJobId(nextRecords, preferredJobId, selectedJobId);
      setRecords(nextRecords);
      setStatusOptions(payload.status_options || []);
      setSelectedJobId(nextJobId);
      onSelectedJobChange(nextJobId);
      if (!nextJobId) setWorkspace(null);
      return nextJobId;
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
      return selectedJobId;
    }
  }

  useEffect(() => {
    loadJobs("");
  }, []);

  useEffect(() => {
    if (!selectedJobId) return;
    setLoadingWorkspace(true);
    apiRequest<JobWorkspacePayload>(`/api/jobs/${selectedJobId}/workspace`)
      .then(setWorkspace)
      .catch((error) => setMessage({ type: "error", text: error.message }))
      .finally(() => setLoadingWorkspace(false));
  }, [selectedJobId]);

  useEffect(() => {
    if (!refreshSignal) return;
    reloadWorkflowFromSignal(refreshJobId, refreshScopes);
  }, [refreshSignal]);

  async function reloadWorkflowFromSignal(preferredJobId: string, scopes: string[]) {
    const refreshJobs = hasAnyRefreshScope(scopes, ["jobs_index", "tracker"]);
    const refreshWorkspace = hasAnyRefreshScope(scopes, ["job_workspace"]);
    if (!refreshJobs && !refreshWorkspace) {
      onRefreshComplete();
      return;
    }

    setLoadingWorkspace(true);
    try {
      const jobsPayload = refreshJobs ? await apiRequest<JobsIndexPayload>("/api/jobs") : null;
      const nextRecords = jobsPayload ? jobsPayload.records || [] : records;
      const nextJobId = refreshJobs
        ? chooseJobId(nextRecords, preferredJobId, selectedJobId)
        : preferredJobId || selectedJobId;
      const workspacePayload = refreshWorkspace && nextJobId
        ? await apiRequest<JobWorkspacePayload>(`/api/jobs/${nextJobId}/workspace`)
        : workspace;
      if (jobsPayload) {
        setRecords(nextRecords);
        setStatusOptions(jobsPayload.status_options || []);
      }
      setSelectedJobId(nextJobId);
      onSelectedJobChange(nextJobId);
      setWorkspace(workspacePayload);
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingWorkspace(false);
      onRefreshComplete();
    }
  }

  async function reloadWorkspace() {
    if (!selectedJobId) return;
    const [workspacePayload, jobsPayload] = await Promise.all([
      apiRequest<JobWorkspacePayload>(`/api/jobs/${selectedJobId}/workspace`),
      apiRequest<JobsIndexPayload>("/api/jobs")
    ]);
    setWorkspace(workspacePayload);
    setRecords(jobsPayload.records || []);
    setStatusOptions(jobsPayload.status_options || []);
    onWorkflowChange(selectedJobId);
  }

  async function reloadJobsAfterRemoval(messageText: string) {
    const jobsPayload = await apiRequest<JobsIndexPayload>("/api/jobs");
    const nextRecords = jobsPayload.records || [];
    setRecords(nextRecords);
    setStatusOptions(jobsPayload.status_options || []);
    const nextJobId = nextRecords[0]?.job_id || "";
    setSelectedJobId(nextJobId);
    onSelectedJobChange(nextJobId);
    setWorkspace(null);
    setMessage({ type: "success", text: messageText });
    onWorkflowChange(nextJobId);
  }

  async function archiveSelectedJob() {
    if (!workspace?.job?.id) return;
    await runBusy((value) => setLoadingWorkspace(value), setMessage, async () => {
      const result = await apiRequest<ApiRecord>(`/api/jobs/${workspace.job.id}/archive`, {
        method: "POST",
        body: JSON.stringify({})
      });
      await reloadJobsAfterRemoval(result.message || "Job removed from active jobs.");
    });
  }

  async function deleteSelectedJob() {
    if (!workspace?.job?.id) return;
    const confirmed = window.confirm(
      `Permanently delete local data for ${workspace.job.company} / ${workspace.job.title}?`
    );
    if (!confirmed) {
      setMessage({ type: "info", text: "Permanent deletion cancelled." });
      return;
    }
    await runBusy((value) => setLoadingWorkspace(value), setMessage, async () => {
      const result = await apiRequest<ApiRecord>(`/api/jobs/${workspace.job.id}`, {
        method: "DELETE",
        body: JSON.stringify({})
      });
      await reloadJobsAfterRemoval(result.message || "Job data permanently deleted.");
    });
  }

  if (!records.length) {
    return (
      <>
        <h1>Jobs</h1>
        <section className="empty-state">
          <h2>No jobs have been added yet.</h2>
          <p className="muted">Jobs appear here after intake and review.</p>
          <button className="primary" onClick={onNavigateToIntake}>Go to Job Intake</button>
        </section>
      </>
    );
  }

  const selectedRecord = records.find((record) => record.job_id === selectedJobId);

  return (
    <>
      <h1>Jobs</h1>
      <StatusMessage type={message?.type} text={message?.text} />
      <div className="jobs-master-detail">
        <aside className="job-list-panel" aria-label="Saved jobs">
          <SectionHeader title="Saved jobs" summary={`${records.length} job${records.length === 1 ? "" : "s"}`} />
          <label className="mobile-job-select">
            Job
            <select
              value={selectedJobId}
              onChange={(event) => {
                setSelectedJobId(event.target.value);
                onSelectedJobChange(event.target.value);
              }}
            >
              {records.map((record) => <option key={record.job_id} value={record.job_id}>{record.company} / {record.title}</option>)}
            </select>
          </label>
          <div className="job-list" role="list">
            {records.map((record) => (
              <button
                className={`job-list-item ${record.job_id === selectedJobId ? "selected" : ""}`}
                key={record.job_id}
                onClick={() => {
                  setSelectedJobId(record.job_id);
                  onSelectedJobChange(record.job_id);
                }}
              >
                <span className="job-list-title">{record.title || "Untitled role"}</span>
                <span className="job-list-company">{record.company || "Unknown company"}</span>
                <span className="job-list-meta">
                  <StatusBadge status={trackerStatusBadge(record.status, statusOptions)} label={trackerStatusLabel(record.status, statusOptions)} />
                  <span>{jobBlockerCount(record, record.job_id === selectedJobId ? workspace : null)} blockers</span>
                </span>
                <span className="job-list-next">{nextWorkspaceAction(record, record.job_id === selectedJobId ? workspace : null)}</span>
              </button>
            ))}
          </div>
        </aside>
        <div className="job-detail-panel">
          {loadingWorkspace && <StatusMessage type="info" text={`Loading workspace for ${selectedRecord?.company || "selected job"}...`} />}
          {!workspace && !loadingWorkspace && <StatusMessage type="info" text="Select a job to load its workflow workspace." />}
          {workspace && (
            <>
              <section className="workflow-overview" aria-label="Selected job workflow">
                <div>
                  <p className="eyebrow">Selected job</p>
                  <h2>{workspace.job.company} / {workspace.job.title}</h2>
                </div>
                <WorkflowStepper workspace={workspace} />
              </section>
              <JobManagement
                agent={agent}
                onArchive={archiveSelectedJob}
                onDelete={deleteSelectedJob}
                busy={loadingWorkspace}
                workspace={workspace}
              />
              <JobSnapshot job={workspace.job} />
              <RequirementsPanel workspace={workspace} setMessage={setMessage} reload={reloadWorkspace} />
              <PackagePanel workspace={workspace} setMessage={setMessage} reload={reloadWorkspace} />
              <FillPlanPanel workspace={workspace} setMessage={setMessage} reload={reloadWorkspace} />
              <ApplyAssistancePanel workspace={workspace} setMessage={setMessage} reload={reloadWorkspace} />
            </>
          )}
        </div>
      </div>
    </>
  );
}
