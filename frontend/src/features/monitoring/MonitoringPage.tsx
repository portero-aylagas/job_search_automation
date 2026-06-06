import { useEffect, useState } from "react";
import { apiRequest } from "../../api";
import { Field, StatusBadge, StatusMessage } from "../../shared/components";
import type { ApiRecord } from "../../shared/types";
import { formatCost, formatDateTime, formatInteger, formatLatency, formatPercent, titleCase } from "../../shared/utils/format";

export function MonitoringPage() {
  const [summary, setSummary] = useState<ApiRecord | null>(null);
  const [windowDays, setWindowDays] = useState(7);
  const [message, setMessage] = useState<ApiRecord | null>({ type: "info", text: "Loading LangSmith monitoring..." });

  async function loadMonitoring(days = windowDays) {
    setMessage({ type: "info", text: "Loading LangSmith monitoring..." });
    try {
      const payload = await apiRequest<ApiRecord>(`/api/monitoring/langsmith?days=${days}`);
      setSummary(payload);
      setMessage(payload.configured ? null : { type: "info", text: payload.message || "LangSmith monitoring is not configured." });
    } catch (error) {
      setSummary(null);
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    loadMonitoring(windowDays);
  }, [windowDays]);

  const totals = summary?.totals || {};
  const extractionTraces = summary?.cv_certificate_traces || [];
  const traceViewLabel = String(summary?.trace_view_label || "CV & Certificates Extraction");
  const traceViewUrl = String(summary?.trace_view_url || "");
  const cvDashboardLabel = String(summary?.cv_extraction_dashboard_label || "job-search-automation_cv-extraction");
  const cvDashboardUrl = String(summary?.cv_extraction_dashboard_url || "");

  return (
    <>
      <h1>Monitoring</h1>
      <p>Review LangSmith activity for the configured project.</p>
      <StatusMessage type={message?.type} text={message?.text} />
      <section className="panel">
        <div className="section-header">
          <div>
            <h2>LangSmith</h2>
            <p className="muted">{summary?.project_name ? `Project: ${summary.project_name}` : "Project not configured"}</p>
          </div>
          <div className="actions">
            <div className="filter-bar compact" aria-label="Monitoring time range">
              {[
                [1, "24h"],
                [7, "7d"],
                [30, "30d"]
              ].map(([days, label]) => (
                <button
                  className={`filter-button ${windowDays === days ? "active" : ""}`}
                  key={days}
                  onClick={() => setWindowDays(Number(days))}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
            {summary?.dashboard_url && (
              <a className="button-link primary" href={summary.dashboard_url} rel="noreferrer" target="_blank">
                Open LangSmith Dashboard
              </a>
            )}
            {cvDashboardUrl && (
              <a className="button-link primary" href={cvDashboardUrl} rel="noreferrer" target="_blank">
                Open {cvDashboardLabel}
              </a>
            )}
          </div>
        </div>
        <div className="grid three monitoring-metrics">
          <Field label="Runs" value={formatInteger(totals.run_count)} />
          <Field label="Total cost" value={formatCost(totals.total_cost)} />
          <Field label="Total tokens" value={formatInteger(totals.total_tokens)} />
          <Field label="Error rate" value={formatPercent(totals.error_rate)} />
          <Field label="Failed runs" value={formatInteger(totals.failed_run_count)} />
          <Field label="Latency p50 / p99" value={`${formatLatency(totals.latency_p50)} / ${formatLatency(totals.latency_p99)}`} />
        </div>
      </section>
      <section className="panel">
        <div className="section-header">
          <div>
            <h2>{traceViewLabel}</h2>
            <p className="muted">LangSmith traces for CV and certificate extraction.</p>
          </div>
          {traceViewUrl && (
            <a className="button-link primary" href={traceViewUrl} rel="noreferrer" target="_blank">
              Open Trace View
            </a>
          )}
        </div>
        {!summary?.configured ? (
          <StatusMessage type="info" text={`Configure LangSmith to show ${traceViewLabel}.`} />
        ) : !extractionTraces.length ? (
          <StatusMessage type="info" text={`No ${traceViewLabel} traces found in the last ${summary.window_days || windowDays} day${(summary.window_days || windowDays) === 1 ? "" : "s"}.`} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                  <th>Trace</th>
                </tr>
              </thead>
              <tbody>
                {extractionTraces.map((run: ApiRecord) => (
                  <tr key={run.id || `${run.name}-${run.start_time}`}>
                    <td>{run.name || "Untitled run"}</td>
                    <td>{run.run_type || "Unknown"}</td>
                    <td>{formatDateTime(run.start_time)}</td>
                    <td><StatusBadge status={run.status === "error" ? "blocked" : "complete"} label={titleCase(run.status || "unknown")} /></td>
                    <td>{formatInteger(run.total_tokens)}</td>
                    <td>{formatCost(run.total_cost)}</td>
                    <td>
                      {run.url ? (
                        <a href={run.url} rel="noreferrer" target="_blank">Open</a>
                      ) : (
                        "Unavailable"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
