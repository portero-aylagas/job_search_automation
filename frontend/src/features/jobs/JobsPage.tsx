import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "../../api";
import { hasAnyRefreshScope } from "../../app/workflowRefresh";
import { AiActionButton, Blockers, DynamicDetails, Field, FillPlanInput, KeyRequirements, List, SectionHeader, StatusBadge, StatusMessage, TextArea, Traceability } from "../../shared/components";
import type {
  ApiRecord,
  ApplicationArtifactPayload,
  ApplicationFillPlanReviewRequest,
  ApplicationFillPlanReviewRow,
  ApplicationFillPlanUploadRow,
  ApplicationPackageReviewRequest,
  ApplicationRequirementsReviewRequest,
  ConfidenceLevel,
  JobIndexRecord,
  JobListingPayload,
  JobsIndexPayload,
  JobWorkspacePayload,
  KarenAgentPayload,
  TrackerStatusOption
} from "../../shared/types";
import { action, runBusy } from "../../shared/utils/apiActions";
import { requirementsToForm } from "../../shared/utils/formData";
import { isCoverLetter, orderArtifacts, titleCase } from "../../shared/utils/format";
import { allWorkspaceBlockers, applyStatus, chooseJobId, fillPlanStatus, jobBlockerCount, jobManagementNextLabel, jobStatus, nextWorkspaceAction, packageStatus, profileStatus, requirementsStatus, reviewSummary, trackerStatusBadge, trackerStatusLabel } from "../../shared/utils/workflow";

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
              <ApplyPanel workspace={workspace} setMessage={setMessage} reload={reloadWorkspace} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

type PanelProps = {
  workspace: JobWorkspacePayload;
  setMessage: (message: ApiRecord | null) => void;
  reload: () => Promise<void> | void;
};

function JobSnapshot({ job }: { job: JobListingPayload }) {
  return (
    <section className="panel" id="workflow-job">
      <SectionHeader title="Job Snapshot" summary={job.apply_url ? "Apply URL present" : "Apply URL missing"} />
      <div className="grid">
        <Field label="Location" value={job.location} />
        <Field label="Remote Policy" value={job.remote_policy} />
        <Field label="Salary" value={job.salary} />
        <Field label="Posted Date" value={job.posted_date} />
        <Field label="Source Job ID" value={job.source_job_id} />
        <p><a href={job.source_url}>Source URL</a>{job.apply_url && <> <a href={job.apply_url}>Apply URL</a></>}</p>
      </div>
      {job.description && <><strong>Role Summary</strong><p>{job.description}</p></>}
      <details><summary>Role details</summary><List title="Requirements" values={job.requirements} /><List title="Responsibilities" values={job.responsibilities} /><List title="Nice-to-have Skills" values={job.nice_to_have_skills} /></details>
      <details><summary>Advanced job details</summary><DynamicDetails details={job.job_details || {}} /></details>
    </section>
  );
}

function WorkflowStepper({ workspace }: { workspace: JobWorkspacePayload }) {
  const steps = [
    { id: "workflow-profile", label: "Profile", ...profileStatus(workspace) },
    { id: "workflow-job", label: "Job", ...jobStatus(workspace) },
    { id: "workflow-requirements", label: "Requirements", ...requirementsStatus(workspace) },
    { id: "workflow-package", label: "Package", ...packageStatus(workspace) },
    { id: "workflow-fill-plan", label: "Fill plan", ...fillPlanStatus(workspace) },
    { id: "workflow-apply", label: "Apply", ...applyStatus(workspace) }
  ];
  return (
    <ol className="workflow-stepper" aria-label="Selected job workflow steps">
      {steps.map((step) => (
        <li className={`workflow-step ${step.status}`} key={step.label}>
          <a href={`#${step.id}`}>
            <span>{step.label}</span>
            <StatusBadge status={step.status} label={step.labelText} />
          </a>
        </li>
      ))}
    </ol>
  );
}

function JobManagement({
  agent,
  onArchive,
  onDelete,
  busy,
  workspace
}: {
  agent: KarenAgentPayload | null;
  onArchive: () => void;
  onDelete: () => void;
  busy: boolean;
  workspace: JobWorkspacePayload;
}) {
  const state = agent?.state || { blockers: [], errors: [], next_allowed_actions: [], pending_gate: null };
  const blockers = [...(state.blockers || []), ...(state.errors || [])].filter(Boolean);
  const nextLabel = jobManagementNextLabel(workspace, state.next_allowed_actions || [], agent?.action_labels);

  return (
    <section className="panel job-management" aria-label="Job management">
      <SectionHeader title="Job Management" />
      <div className="actions split-actions">
        <button className="secondary" onClick={onArchive} disabled={busy}>
          Remove from active jobs
        </button>
        <button className="danger" onClick={onDelete} disabled={busy}>
          Permanently delete job data
        </button>
      </div>
      <div className="job-management-summary" aria-label="Selected job workflow summary">
        <div>
          <span className="summary-label">Gate</span>
          <strong>{state.pending_gate ? titleCase(state.pending_gate) : "None"}</strong>
        </div>
        <div>
          <span className="summary-label">Blockers</span>
          <strong>{blockers.length}</strong>
        </div>
        <div>
          <span className="summary-label">Next</span>
          <strong>{nextLabel}</strong>
        </div>
      </div>
      <Blockers title="Workflow blockers" blockers={blockers} />
    </section>
  );
}

function RequirementsPanel({ workspace, setMessage, reload }: PanelProps) {
  const requirements = workspace.requirements;
  const [form, setForm] = useState<ApplicationRequirementsReviewRequest>(() => requirementsToForm(requirements));
  const [discovering, setDiscovering] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  useEffect(() => setForm(requirementsToForm(requirements)), [requirements?.job_id, requirements?.review_status]);
  const buttonLabel = requirements ? "Refresh requirements from apply URL with AI" : "Discover requirements from apply URL with AI";
  const pendingLabel = requirements ? "Refreshing requirements..." : "Discovering requirements...";

  async function discover() {
    setDiscovering(true);
    try {
      await action(`/api/jobs/${workspace.job.id}/requirements/discover`, "POST", {}, setMessage, reload);
    } finally {
      setDiscovering(false);
    }
  }

  async function saveReview(event: FormEvent) {
    event.preventDefault();
    await runBusy(setSavingReview, setMessage, async () => {
      await action(`/api/jobs/${workspace.job.id}/requirements/review`, "PUT", form, setMessage, reload);
    });
  }

  return (
    <section className="panel" id="workflow-requirements">
      <fieldset aria-busy={discovering || savingReview} className="ai-blocking-surface" disabled={discovering || savingReview}>
        <SectionHeader
          title="Application Requirements"
          summary={requirements ? reviewSummary(requirements.review_status, requirements.confidence) : "Not discovered"}
        />
        <div className="badge-row">
          <StatusBadge status={requirementsStatus(workspace).status} label={requirementsStatus(workspace).labelText} />
          {requirements?.confidence && <StatusBadge status={requirements.confidence === "low" ? "low-confidence" : "reviewed"} label={`Confidence: ${requirements.confidence}`} />}
          {requirements?.source_evidence?.length ? <StatusBadge status="ready" label={`${requirements.source_evidence.length} evidence item${requirements.source_evidence.length === 1 ? "" : "s"}`} /> : null}
        </div>
        {!workspace.job.apply_url && <StatusMessage type="warning" text="Apply URL is missing. Requirements discovery is blocked." />}
        <p className="muted">This action fetches the apply page and uses AI to interpret requirements.</p>
        <div className="actions">
          <AiActionButton
            className={requirements ? "secondary" : "primary"}
            isPending={discovering}
            label={buttonLabel}
            onClick={discover}
            pendingLabel={pendingLabel}
          />
        </div>
        {!requirements && <StatusMessage type="info" text="No application requirements have been discovered yet." />}
        {requirements && (
          <form onSubmit={saveReview}>
            {requirements.blocked_reason && <StatusMessage type="warning" text={requirements.blocked_reason} />}
            <KeyRequirements requirements={requirements} />
            <label className="check-row"><input type="checkbox" checked={!!form.job_preserving} onChange={(event) => setForm((current) => ({ ...current, job_preserving: event.target.checked }))} />Apply page matches this selected job</label>
            <label>Overall confidence<select value={form.confidence} onChange={(event) => setForm((current) => ({ ...current, confidence: event.target.value as ConfidenceLevel }))}>{["low", "medium", "high"].map((value) => <option key={value}>{value}</option>)}</select></label>
            {[
              ["Blocked reason", "blocked_reason"],
              ["Required documents", "required_documents_text"],
              ["Upload expectations", "upload_expectations_text"],
              ["Profile fields requested", "profile_fields_text"],
              ["Screening questions", "screening_questions_text"],
              ["Custom form fields", "custom_form_fields_text"],
              ["Consent requirements", "consent_requirements_text"],
              ["Privacy, login, and ATS gates", "privacy_login_ats_gates_text"],
              ["Deadlines", "deadlines_text"],
              ["Contact / fallback info", "contact_or_fallback_text"],
              ["Missing or uncertain", "missing_or_uncertain_text"]
            ].map(([label, key]) => <TextArea key={key} label={label} value={form[key] || ""} onChange={(value) => setForm((current) => ({ ...current, [key]: value }))} />)}
            <div className="grid">
              <label>Motivation / cover letter requirement<input value={form.motivation_label || ""} onChange={(event) => setForm((current) => ({ ...current, motivation_label: event.target.value }))} /></label>
              <label className="check-row"><input type="checkbox" checked={!!form.motivation_required} onChange={(event) => setForm((current) => ({ ...current, motivation_required: event.target.checked }))} />Motivation / cover letter is required</label>
            </div>
            <details><summary>Requirements evidence</summary><List title="Source Evidence" values={requirements.source_evidence} /></details>
            <div className="actions">
              <AiActionButton
                className="primary"
                isPending={savingReview}
                label="Save requirements review"
                pendingLabel="Saving requirements review..."
                type="submit"
              />
            </div>
          </form>
        )}
      </fieldset>
    </section>
  );
}

function PackagePanel({ workspace, setMessage, reload }: PanelProps) {
  const packageData = workspace.package;
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [destination, setDestination] = useState("");
  const [generating, setGenerating] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    const next: Record<string, string> = {};
    (packageData?.artifacts || []).forEach((artifact: ApplicationArtifactPayload) => {
      next[artifact.id] = artifact.content || "";
    });
    setEdits(next);
    setDestination(`/home/javi/projects/ironhack_AI_integration/ironhack_projects/job_search_automation/outputs/${workspace.job.id}/artifacts`);
  }, [packageData?.job_id, workspace.job.id]);
  const buttonLabel = packageData ? "Regenerate application package with AI" : "Generate application package with AI";
  const pendingLabel = packageData ? "Regenerating application package..." : "Generating application package...";

  async function generatePackage() {
    setGenerating(true);
    try {
      await action(`/api/jobs/${workspace.job.id}/package/generate`, "POST", {}, setMessage, reload);
    } finally {
      setGenerating(false);
    }
  }

  async function saveReview(event: FormEvent) {
    event.preventDefault();
    await runBusy(setSavingReview, setMessage, async () => {
      const payload: ApplicationPackageReviewRequest = { edits_by_artifact_id: edits };
      await action(`/api/jobs/${workspace.job.id}/package/review`, "PUT", payload, setMessage, reload);
    });
  }

  async function exportCoverLetter() {
    await runBusy(setExporting, setMessage, async () => {
      await action(`/api/jobs/${workspace.job.id}/package/export-cover-letter`, "POST", { destination_folder: destination }, setMessage, reload);
    });
  }

  return (
    <section className="panel" id="workflow-package">
      <fieldset aria-busy={generating || savingReview || exporting} className="ai-blocking-surface" disabled={generating || savingReview || exporting}>
        <SectionHeader
          title="Application Package"
          summary={packageData ? reviewSummary(packageData.status || packageData.review_status) : "Not generated"}
        />
        <div className="badge-row">
          <StatusBadge status={packageStatus(workspace).status} label={packageStatus(workspace).labelText} />
          {packageData?.status && <StatusBadge status={packageData.status === "approved" ? "reviewed" : "needs-review"} label={`Status: ${titleCase(packageData.status)}`} />}
        </div>
        <Blockers title="Application package generation is blocked until these prerequisites are complete:" blockers={workspace.package_blockers} />
        <p className="muted">This action uses AI to draft application materials from reviewed data.</p>
        <div className="actions">
          <AiActionButton
            className={packageData ? "secondary" : "primary"}
            disabled={!!workspace.package_blockers?.length}
            isPending={generating}
            label={buttonLabel}
            onClick={generatePackage}
            pendingLabel={pendingLabel}
          />
        </div>
        {!packageData && <StatusMessage type="info" text="No application package has been generated yet." />}
        {packageData && (
          <>
            <List title="Selected Experience Units" values={workspace.package_summary?.selected_experience_units || []} />
            <form onSubmit={saveReview}>
              {orderArtifacts(packageData.artifacts || []).map((artifact: ApplicationArtifactPayload) => (
                <details key={artifact.id} open={isCoverLetter(artifact)}>
                  <summary>{artifact.label}</summary>
                  {artifact.source_prompt && <p className="muted">Source prompt: {artifact.source_prompt}</p>}
                  {artifact.source_requirement && <p className="muted">Source requirement: {artifact.source_requirement}</p>}
                  <TextArea label={`${artifact.label} content`} value={edits[artifact.id] || ""} onChange={(value) => setEdits((current) => ({ ...current, [artifact.id]: value }))} />
                  <Traceability metadata={artifact.metadata || {}} />
                </details>
              ))}
              <div className="actions">
                <AiActionButton
                  className="primary"
                  isPending={savingReview}
                  label="Save package review"
                  pendingLabel="Saving package review..."
                  type="submit"
                />
              </div>
            </form>
            {packageData.artifacts?.some(isCoverLetter) && (
              <div className="workflow-subsection">
                <h3>Cover Letter Artifact</h3>
                <label>Cover letter destination folder<input value={destination} onChange={(event) => setDestination(event.target.value)} /></label>
                <div className="actions">
                  <AiActionButton
                    className="secondary"
                    isPending={exporting}
                    label="Export cover letter PDF"
                    onClick={exportCoverLetter}
                    pendingLabel="Exporting cover letter..."
                  />
                </div>
              </div>
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}

function FillPlanPanel({ workspace, setMessage, reload }: PanelProps) {
  const fillPlan = workspace.fill_plan;
  const review = workspace.fill_plan_review;
  const [values, setValues] = useState<Record<string, string>>({});
  const [uploads, setUploads] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  useEffect(() => {
    const nextValues: Record<string, string> = {};
    const nextUploads: Record<string, string> = {};
    [...(review?.required_rows || []), ...(review?.optional_rows || [])].forEach((row: ApplicationFillPlanReviewRow) => {
      nextValues[row.edit_key] = row.value || "";
    });
    (review?.upload_rows || []).forEach((row: ApplicationFillPlanUploadRow) => {
      nextUploads[row.edit_key] = row.file_path || "";
    });
    setValues(nextValues);
    setUploads(nextUploads);
  }, [fillPlan?.job_id, fillPlan?.review_status]);
  const buttonLabel = fillPlan ? "Refresh fill plan with AI" : "Generate fill plan with AI";
  const pendingLabel = fillPlan ? "Refreshing fill plan..." : "Generating fill plan...";

  async function generateFillPlan() {
    setGenerating(true);
    try {
      await action(`/api/jobs/${workspace.job.id}/fill-plan/generate`, "POST", {}, setMessage, reload);
    } finally {
      setGenerating(false);
    }
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    const edited_values: Record<string, string> = {};
    const needs_answer_values_by_key: Record<string, string> = {};
    const blocked_values_by_key: Record<string, string> = {};
    [...(review?.required_rows || []), ...(review?.optional_rows || [])].forEach((row: ApplicationFillPlanReviewRow) => {
      if (row.kind === "field") edited_values[row.edit_key] = values[row.edit_key] || "";
      if (row.kind === "needs") needs_answer_values_by_key[row.edit_key] = values[row.edit_key] || "";
      if (row.kind === "blocked") blocked_values_by_key[row.edit_key] = values[row.edit_key] || "";
    });
    await runBusy(setSavingReview, setMessage, async () => {
      const payload: ApplicationFillPlanReviewRequest = {
        edited_values,
        upload_paths_by_key: uploads,
        needs_answer_values_by_key,
        blocked_values_by_key
      };
      await action(`/api/jobs/${workspace.job.id}/fill-plan/review`, "PUT", payload, setMessage, reload);
    });
  }

  return (
    <section className="panel" id="workflow-fill-plan">
      <fieldset aria-busy={generating || savingReview} className="ai-blocking-surface" disabled={generating || savingReview}>
        <SectionHeader
          title="Application Fill Plan"
          summary={fillPlan ? reviewSummary(fillPlan.review_status) : "Not generated"}
        />
        <div className="badge-row">
          <StatusBadge status={fillPlanStatus(workspace).status} label={fillPlanStatus(workspace).labelText} />
          {review && <StatusBadge status="ready" label={`${(review.required_rows || []).length} required fields`} />}
        </div>
        <Blockers title="Fill plan generation is blocked until these steps are complete:" blockers={workspace.fill_plan_generation_blockers} />
        <div className="actions">
          <AiActionButton
            className={fillPlan ? "secondary" : "primary"}
            disabled={!!workspace.fill_plan_generation_blockers?.length}
            isPending={generating}
            label={buttonLabel}
            onClick={generateFillPlan}
            pendingLabel={pendingLabel}
          />
        </div>
        {!fillPlan && <StatusMessage type="info" text="No application fill plan has been generated yet." />}
        {fillPlan && review && (
          <form onSubmit={submitReview}>
            <p className="muted">Prefilled values are ready to save. Edit only the fields that need a correction before Browser Use receives them.</p>
            <div className="workflow-subsection">
              <h3>Required fields</h3>
              {!review.required_rows?.length && <p className="muted">No required fields.</p>}
              {review.required_rows?.map((row) => <FillPlanInput key={row.edit_key} row={row} value={values[row.edit_key] || ""} onChange={(value) => setValues((current) => ({ ...current, [row.edit_key]: value }))} />)}
            </div>
            <div className="workflow-subsection">
              <h3>Uploads Sent To Browser</h3>
              {!review.upload_rows?.length && <p className="muted">No uploads sent to browser.</p>}
              {review.upload_rows?.map((row) => <label key={row.edit_key}>{row.label} file path<input value={uploads[row.edit_key] || ""} onChange={(event) => setUploads((current) => ({ ...current, [row.edit_key]: event.target.value }))} /></label>)}
            </div>
            <details><summary>Optional or unclear</summary>{!review.optional_rows?.length && <p className="muted">No optional or unclear fields.</p>}{review.optional_rows?.map((row) => <FillPlanInput key={row.edit_key} row={row} value={values[row.edit_key] || ""} onChange={(value) => setValues((current) => ({ ...current, [row.edit_key]: value }))} />)}</details>
            <div className="actions">
              <AiActionButton
                className="primary"
                isPending={savingReview}
                label="Save fill plan review"
                pendingLabel="Saving fill plan review..."
                type="submit"
              />
            </div>
          </form>
        )}
      </fieldset>
    </section>
  );
}

function ApplyPanel({ workspace, setMessage, reload }: PanelProps) {
  const [applying, setApplying] = useState(false);
  const [stoppingSession, setStoppingSession] = useState(false);
  const [killingProcesses, setKillingProcesses] = useState(false);
  const [applyMessage, setApplyMessage] = useState<ApiRecord | null>(null);
  const staleRunnerCount =
    Math.max(
      0,
      Number(workspace.browser_use_runner_count || 0) -
        (workspace.active_browser_use_session ? 1 : 0)
    );

  async function applyWithAi() {
    setApplying(true);
    setApplyMessage({ type: "info", text: "Starting Browser Use apply agent..." });
    try {
      const result = await apiRequest<ApiRecord>(`/api/jobs/${workspace.job.id}/apply`, {
        method: "POST",
        body: JSON.stringify({})
      });
      setApplyMessage({ type: "success", text: result.message || "Started Browser Use apply agent." });
      setMessage({ type: "success", text: result.message || "Started Browser Use apply agent." });
      reload();
    } catch (error) {
      setApplyMessage({
        type: "error",
        text: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setApplying(false);
    }
  }

  async function stopBrowserSession() {
    await runBusy(setStoppingSession, setMessage, async () => {
      await action(`/api/jobs/${workspace.job.id}/browser/stop-session`, "POST", {}, setMessage, reload);
    });
  }

  async function killBrowserProcesses() {
    await runBusy(setKillingProcesses, setMessage, async () => {
      await action(`/api/jobs/${workspace.job.id}/browser/kill-all`, "POST", {}, setMessage, reload);
    });
  }

  return (
    <section className="panel" id="workflow-apply">
      <fieldset aria-busy={applying || stoppingSession || killingProcesses} className="ai-blocking-surface" disabled={applying || stoppingSession || killingProcesses}>
        <SectionHeader
          title="Apply to position"
          summary={workspace.apply_blockers?.length ? "Blocked" : "Ready"}
        />
        <div className="badge-row">
          <StatusBadge status={applyStatus(workspace).status} label={applyStatus(workspace).labelText} />
          {workspace.active_browser_use_session ? <StatusBadge status="needs-review" label="Browser session active" /> : <StatusBadge status="ready" label="Browser idle" />}
        </div>
        <h3>Apply Assistance</h3>
        <Blockers title="Apply assistance is blocked until these review steps are complete:" blockers={workspace.apply_blockers} />
        <StatusMessage type={applyMessage?.type} text={applyMessage?.text} />
        {staleRunnerCount > 0 && (
          <StatusMessage
            type="warning"
            text={`${staleRunnerCount} Browser Use runner process is active outside the tracked session. Use Kill All Browser Use Processes before applying again.`}
          />
        )}
        <details open={staleRunnerCount > 0}>
          <summary>Browser process controls</summary>
          {workspace.active_browser_use_session ? <StatusMessage type="info" text={`Browser Use session running: PID ${workspace.active_browser_use_session.pid} for ${workspace.active_browser_use_session.url}`} /> : <p className="muted">Browser Use session status: idle.</p>}
          <div className="actions">
            <AiActionButton
              className="secondary"
              isPending={stoppingSession}
              label="Stop Browser Use Session"
              onClick={stopBrowserSession}
              pendingLabel="Stopping Browser Use Session..."
            />
            <AiActionButton
              className="danger"
              isPending={killingProcesses}
              label="Kill All Browser Use Processes"
              onClick={killBrowserProcesses}
              pendingLabel="Killing Browser Use Processes..."
            />
          </div>
        </details>
        <p className="muted">This action opens the reviewed apply URL and asks Browser Use to execute the reviewed application fill plan.</p>
        <div className="actions">
          <AiActionButton
            className="primary"
            disabled={!!workspace.apply_blockers?.length || applying}
            isPending={applying}
            label="Apply to job with AI"
            onClick={applyWithAi}
            pendingLabel="Starting AI apply assistance..."
          />
        </div>
      </fieldset>
    </section>
  );
}
