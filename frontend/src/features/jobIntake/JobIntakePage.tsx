import { FormEvent, useState } from "react";
import { apiRequest } from "../../api";
import { AiActionButton, SectionHeader, StatusBadge, StatusMessage, TextArea } from "../../shared/components";
import type { ApiRecord } from "../../shared/types";
import { runBusy } from "../../shared/utils/apiActions";
import { textFields, updateDynamicField } from "../../shared/utils/formData";

export function JobIntakePage({ onSaved }: { onSaved: (jobId: string) => void }) {
  const [sourceUrl, setSourceUrl] = useState("");
  const [extraction, setExtraction] = useState<ApiRecord | null>(null);
  const [form, setForm] = useState<ApiRecord>({});
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);

  async function extract(event: FormEvent) {
    event.preventDefault();
    await runBusy(setExtracting, setMessage, async () => {
      const result = await apiRequest<ApiRecord>("/api/job-intake/extract", {
        method: "POST",
        body: JSON.stringify({ source_url: sourceUrl })
      });
      setExtraction(result);
      const data = result.extracted_data;
      setForm({
        title: data.title || "",
        company: data.company || "",
        location: data.location || "",
        remote_policy: data.remote_policy || "",
        apply_url: result.final_apply_url || "",
        salary: data.salary || "",
        posted_date: data.posted_date || "",
        source_job_id: data.source_job_id || "",
        description: data.description || "",
        requirements: (data.requirements || []).join("\n"),
        responsibilities: (data.responsibilities || []).join("\n"),
        nice_to_have_skills: (data.nice_to_have_skills || []).join("\n"),
        dynamic_fields: (data.dynamic_fields || []).map((field: ApiRecord, index: number) => ({
          dynamic: true,
          name: field.name || `Additional Detail ${index + 1}`,
          value: field.value || "",
          category: field.category || "",
          source_text: field.source_text || "",
          confidence: field.confidence || "medium"
        }))
      });
    });
  }

  async function saveReviewedJob(event: FormEvent) {
    event.preventDefault();
    if (!extraction) return;
    await runBusy(setSaving, setMessage, async () => {
      const result = await apiRequest<ApiRecord>("/api/job-intake/save", {
        method: "POST",
        body: JSON.stringify({
          source_url: extraction.source_url,
          extracted_data: extraction.extracted_data,
          apply_resolution: extraction.apply_resolution,
          ...form
        })
      });
      setMessage({ type: "success", text: result.message });
      setExtraction(null);
      onSaved(result.job?.job_id || result.job?.id || "");
    });
  }

  return (
    <>
      <h1>Job Intake</h1>
      <p>Generate application data from a job URL.</p>
      <StatusMessage type={message?.type} text={message?.text} />
      <fieldset aria-busy={extracting || saving} className="ai-blocking-surface" disabled={extracting || saving}>
        <section className="panel">
          <SectionHeader title="Source URL" summary={sourceUrl ? "Ready to extract" : "Waiting for job URL"} />
          <form onSubmit={extract}>
            <label>Job URL<input placeholder="https://company.com/jobs/role" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></label>
            <div className="actions">
              <AiActionButton
                className="primary"
                disabled={saving}
                isPending={extracting}
                label="Extract application data with AI"
                pendingLabel="Extracting application data..."
                type="submit"
              />
            </div>
          </form>
        </section>
        {extraction && (
        <section className="panel">
          <SectionHeader
            title="Review Extracted Data"
            summary={extraction.extracted_data?.missing_or_uncertain?.length ? "Needs review" : "Ready to save"}
          />
          <p className="muted">Review what the AI found before adding it to the application workflow.</p>
          <div className="badge-row">
            <StatusBadge status={extraction.extracted_data?.missing_or_uncertain?.length ? "needs-review" : "ready"} />
            <StatusBadge status={extraction.apply_resolution?.confidence === "low" ? "low-confidence" : "reviewed"} label={`Apply URL confidence: ${extraction.apply_resolution?.confidence || "unknown"}`} />
          </div>
          {extraction.apply_resolution?.status !== "resolved" && <StatusMessage type="warning" text={extraction.apply_resolution?.notes || "The application destination could not be verified automatically."} />}
          {(extraction.apply_url_messages?.errors || []).map((item: string) => <StatusMessage key={item} type="error" text={item} />)}
          {(extraction.apply_url_messages?.warnings || []).map((item: string) => <StatusMessage key={item} type="warning" text={item} />)}
          {(extraction.apply_url_messages?.info || []).map((item: string) => <StatusMessage key={item} type="info" text={item} />)}
          <form onSubmit={saveReviewedJob}>
            <div className="grid">
              {textFields(["Title", "Company", "Location", "Remote Policy"], ["title", "company", "location", "remote_policy"], form, setForm)}
              {textFields(["Apply URL", "Salary", "Posted Date", "Source Job ID"], ["apply_url", "salary", "posted_date", "source_job_id"], form, setForm)}
            </div>
            <TextArea label="Role Summary" value={form.description || ""} onChange={(value) => setForm((current) => ({ ...current, description: value }))} />
            <TextArea label="Requirements" value={form.requirements || ""} onChange={(value) => setForm((current) => ({ ...current, requirements: value }))} />
            <TextArea label="Responsibilities" value={form.responsibilities || ""} onChange={(value) => setForm((current) => ({ ...current, responsibilities: value }))} />
            <TextArea label="Nice-to-have Skills" value={form.nice_to_have_skills || ""} onChange={(value) => setForm((current) => ({ ...current, nice_to_have_skills: value }))} />
            <h3>Additional Extracted Details</h3>
            {form.dynamic_fields?.length ? form.dynamic_fields.map((field: ApiRecord, index: number) => (
              <label key={`${field.name}-${index}`}>
                <span className="label-with-meta">
                  {field.name}
                  <StatusBadge status={field.confidence === "low" ? "low-confidence" : "reviewed"} label={`Confidence: ${field.confidence || "unknown"}`} />
                </span>
                <input aria-label={field.name || `Additional Detail ${index + 1}`} value={field.value || ""} onChange={(event) => updateDynamicField(index, event.target.value, setForm)} />
                {field.source_text && <span className="field-hint">Source: {field.source_text}</span>}
              </label>
            )) : <p className="muted">No additional details were extracted.</p>}
            {extraction.extracted_data?.missing_or_uncertain?.length ? <StatusMessage type="warning" text={`Needs review: ${extraction.extracted_data.missing_or_uncertain.join("; ")}`} /> : null}
            <div className="actions">
              <AiActionButton
                className="primary"
                disabled={saving}
                isPending={saving}
                label="Add To Application Workflow"
                pendingLabel="Adding to workflow..."
                type="submit"
              />
            </div>
          </form>
        </section>
        )}
      </fieldset>
    </>
  );
}
