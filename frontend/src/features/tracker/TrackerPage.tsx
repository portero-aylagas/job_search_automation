import { useEffect, useState } from "react";
import { apiRequest } from "../../api";
import { hasAnyRefreshScope } from "../../app/workflowRefresh";
import { StatusBadge, StatusMessage } from "../../shared/components";
import type { ApiRecord } from "../../shared/types";
import { formatDateTime } from "../../shared/utils/format";
import { jobBlockerCount, nextWorkspaceAction, trackerStatusBadge, trackerStatusLabel } from "../../shared/utils/workflow";

export function TrackerPage({
  onRefreshComplete,
  onWorkflowChange,
  refreshScopes,
  refreshSignal
}: {
  onRefreshComplete: () => void;
  onWorkflowChange: (jobId?: string, nextSessionId?: string) => void;
  refreshScopes: string[];
  refreshSignal: number;
}) {
  const [records, setRecords] = useState<ApiRecord[]>([]);
  const [statusOptions, setStatusOptions] = useState<ApiRecord[]>([]);
  const [statusFilters, setStatusFilters] = useState<ApiRecord[]>([]);
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [statusFilter, setStatusFilter] = useState("All");

  async function loadTracker() {
    try {
      const payload = await apiRequest<ApiRecord>("/api/tracker");
      setRecords(payload.records || []);
      setStatusOptions(payload.status_options || []);
      setStatusFilters(payload.status_filters || []);
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    if (refreshSignal && !hasAnyRefreshScope(refreshScopes, ["tracker", "jobs_index"])) {
      onRefreshComplete();
      return;
    }
    loadTracker().finally(() => {
      if (refreshSignal) onRefreshComplete();
    });
  }, [refreshSignal]);

  async function updateRecordStatus(jobId: string, status: string) {
    try {
      const payload = await apiRequest<ApiRecord>(`/api/tracker/${jobId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      const updatedRecord = payload.record || {};
      setRecords((current) => current.map((record) => (
        record.job_id === jobId ? { ...record, ...updatedRecord } : record
      )));
      setStatusOptions(payload.status_options || statusOptions);
      setStatusFilters(payload.status_filters || statusFilters);
      setMessage({ type: "info", text: payload.message || "Tracker status updated." });
      onWorkflowChange(jobId);
    } catch (error: any) {
      setMessage({ type: "error", text: error.message });
    }
  }

  async function deleteRecord(jobId: string) {
    const record = records.find((item) => item.job_id === jobId);
    const label = record ? `${record.company || "Unknown company"} / ${record.title || "Untitled role"}` : jobId;
    if (!window.confirm(`Permanently delete local data for ${label}?`)) {
      setMessage({ type: "info", text: "Permanent deletion cancelled." });
      return;
    }
    try {
      const payload = await apiRequest<ApiRecord>(`/api/jobs/${jobId}`, {
        method: "DELETE",
        body: JSON.stringify({})
      });
      setRecords((current) => current.filter((item) => item.job_id !== jobId));
      setMessage({ type: "success", text: payload.message || "Job data permanently deleted." });
      onWorkflowChange();
    } catch (error: any) {
      setMessage({ type: "error", text: error.message });
    }
  }

  const filteredRecords = records.filter((record) => {
    if (statusFilter === "All") return true;
    const filter = statusFilters.find((item) => item.label === statusFilter);
    return (filter?.statuses || []).includes(record.status);
  });
  return (
    <>
      <h1>Tracker</h1>
      <StatusMessage type={message?.type} text={message?.text} />
      {!records.length ? (
        <section className="empty-state">
          <h2>No tracker records yet.</h2>
          <p className="muted">Jobs appear in the tracker after intake creates an application workspace.</p>
        </section>
      ) : (
        <>
          <div className="filter-bar" aria-label="Tracker status filters">
            {statusFilters.map((filter) => (
              <button
                className={`filter-button ${statusFilter === filter.label ? "active" : ""}`}
                key={filter.label}
                onClick={() => setStatusFilter(filter.label)}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <TrackerTable
            records={filteredRecords}
            statusOptions={statusOptions}
            onStatusChange={updateRecordStatus}
            onDeleteJob={deleteRecord}
          />
        </>
      )}
    </>
  );
}

function TrackerTable({
  records,
  statusOptions,
  onStatusChange,
  onDeleteJob
}: {
  records: ApiRecord[];
  statusOptions: ApiRecord[];
  onStatusChange: (jobId: string, status: string) => void;
  onDeleteJob: (jobId: string) => void;
}) {
  if (!records.length) return <StatusMessage type="info" text="No tracker records match this filter." />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {["Company", "Title", "Status", "Next action", "Blockers", "Last updated", "Links", ""].map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record, index) => (
            <tr key={record.job_id || index}>
              <td>{record.company || "Unknown company"}</td>
              <td>{record.title || "Untitled role"}</td>
              <td>
                <div className="status-cell">
                  <StatusBadge status={trackerStatusBadge(record.status, statusOptions)} label={trackerStatusLabel(record.status, statusOptions)} />
                  <select
                    aria-label={`Status for ${record.company || "Unknown company"} / ${record.title || "Untitled role"}`}
                    value={record.status || "new"}
                    onChange={(event) => onStatusChange(record.job_id, event.target.value)}
                  >
                    {statusOptions.map((option) => (
                      <option
                        disabled={!option.user_editable && option.value !== record.status}
                        key={option.value}
                        value={option.value}
                      >
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
              </td>
              <td>{nextWorkspaceAction(record, null)}</td>
              <td>{jobBlockerCount(record, null)}</td>
              <td>{formatDateTime(record.last_updated || record.updated_at || record.created_at)}</td>
              <td>
                <div className="link-list">
                  {record.source_url && <a href={record.source_url}>Source</a>}
                  {record.apply_url && <a href={record.apply_url}>Apply</a>}
                </div>
              </td>
              <td>
                <button
                  aria-label={`Delete ${record.company || "Unknown company"} / ${record.title || "Untitled role"}`}
                  className="icon-button danger"
                  onClick={() => onDeleteJob(record.job_id)}
                  title="Permanently delete job data"
                  type="button"
                >
                  X
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
