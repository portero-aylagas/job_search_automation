import { useEffect, useState } from "react";
import { apiRequest, fileToPayload } from "../../api";
import { hasAnyRefreshScope } from "../../app/workflowRefresh";
import { AiActionButton, CheckboxGroup, SectionHeader, StatusMessage, TextArea } from "../../shared/components";
import type { ApiRecord } from "../../shared/types";
import { runBusy, saveProfileDraft } from "../../shared/utils/apiActions";
import { blockTextFromItems, blocksFromText, linesFromText, optionalNumber, textFromItems, updateNested } from "../../shared/utils/formData";
import { basename } from "../../shared/utils/format";
import { careerLevel, employmentType, genderOptions, remotePreference, workAuthorization } from "./options";

export function CandidateProfilePage({
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
  const [profile, setProfile] = useState<ApiRecord | null>(null);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [optionalFiles, setOptionalFiles] = useState<Record<string, File[]>>({
    reference: [],
    certificate: [],
    other: []
  });
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const isAiPending = !!pendingAction;

  async function loadProfile() {
    try {
      const payload = await apiRequest<ApiRecord>("/api/candidate-profile");
      setProfile(payload.profile);
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    if (refreshSignal && !hasAnyRefreshScope(refreshScopes, ["candidate_profile"])) {
      onRefreshComplete();
      return;
    }
    loadProfile().finally(() => {
      if (refreshSignal) onRefreshComplete();
    });
  }, [refreshSignal]);

  const extracted = profile?.candidate_profile?.cv_extracted;
  const preferences = profile?.candidate_profile?.candidate_preferences;
  const sourceDocuments = profile?.candidate_profile?.source_documents;

  function updateIdentity(field: string, value: string) {
    setProfile((current) => updateNested(current, ["candidate_profile", "cv_extracted", "identity", field], value));
  }

  function updateExtractedList(field: string, value: string, block = false) {
    const parsed = block ? blocksFromText(value) : linesFromText(value);
    setProfile((current) => updateNested(current, ["candidate_profile", "cv_extracted", field], parsed));
  }

  function updatePreference(field: string, value: any) {
    setProfile((current) => updateNested(current, ["candidate_profile", "candidate_preferences", field], value));
  }

  async function parseCv() {
    if (!cvFile) {
      setMessage({ type: "error", text: "Upload a CV before parsing." });
      return;
    }
    await runBusy((value) => setPendingAction(value ? "parse-cv" : null), setMessage, async () => {
      const payload = await fileToPayload(cvFile);
      const result = await apiRequest<ApiRecord>("/api/candidate-profile/parse-cv", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setProfile(result.profile);
      setMessage({ type: "success", text: result.message });
      onWorkflowChange();
    });
  }

  async function parseOptionalDocuments() {
    const entries = Object.entries(optionalFiles).flatMap(([documentType, files]) =>
      files.map((file) => [documentType, file] as const)
    );
    if (!entries.length) {
      setMessage({ type: "error", text: "Upload at least one optional document before parsing." });
      return;
    }
    await runBusy((value) => setPendingAction(value ? "parse-optional-documents" : null), setMessage, async () => {
      let nextProfile = profile;
      for (const [documentType, file] of entries) {
        const payload = await fileToPayload(file, documentType);
        const result = await apiRequest<ApiRecord>("/api/candidate-profile/parse-optional-document", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        nextProfile = result.profile;
      }
      setProfile(nextProfile);
      setMessage({ type: "success", text: `Parsed ${entries.length} optional document${entries.length === 1 ? "" : "s"} into the review fields.` });
      onWorkflowChange();
    });
  }

  async function saveReview() {
    if (!profile) return;
    await runBusy((value) => setPendingAction(value ? "save-review" : null), setMessage, async () => {
      await saveProfileDraft("/api/candidate-profile/review-changes", profile, setProfile, setMessage);
      onWorkflowChange();
    });
  }

  async function savePreferences() {
    if (!profile) return;
    await runBusy((value) => setPendingAction(value ? "save-preferences" : null), setMessage, async () => {
      await saveProfileDraft("/api/candidate-profile/preferences", profile, setProfile, setMessage);
      onWorkflowChange();
    });
  }

  async function deleteUploadedDocument(filePath: string, documentType: string, label: string) {
    if (!filePath.trim()) {
      setMessage({ type: "error", text: "The selected document is missing a file path." });
      return;
    }
    if (!window.confirm(`Delete ${label}?`)) return;
    await runBusy((value) => setPendingAction(value ? `delete:${filePath}` : null), setMessage, async () => {
      const result = await apiRequest<ApiRecord>("/api/candidate-profile/document", {
        method: "DELETE",
        body: JSON.stringify({
          file_path: filePath,
          document_type: documentType
        })
      });
      setProfile(result.profile);
      if (documentType === "cv") {
        setCvFile(null);
      } else {
        setOptionalFiles((current) => ({
          ...current,
          [documentType]: []
        }));
      }
      setMessage({ type: "success", text: result.message });
      onWorkflowChange();
    });
  }

  if (message?.type === "error" && (!profile || !extracted || !preferences || !sourceDocuments)) {
    return <StatusMessage type="error" text={message.text} />;
  }

  if (!profile || !extracted || !preferences || !sourceDocuments) {
    return <StatusMessage type="info" text="Loading candidate profile..." />;
  }

  return (
    <>
      <h1>Candidate Profile</h1>
      <p>Upload your CV and certifications once, review the extracted data, and optionally add job-search preferences for future discovery.</p>
      <StatusMessage type={message?.type} text={message?.text} />
      <fieldset aria-busy={isAiPending} className="ai-blocking-surface" disabled={isAiPending}>
        <section className="panel" id="workflow-profile">
          <SectionHeader title="1. CV Upload" summary={sourceDocuments.cv?.parsed ? "CV parsed" : "CV needs parsing"} />
          <p className="muted">The CV is the source of truth for professional data.</p>
          {sourceDocuments.cv?.file_path && (
            <div className="uploaded-document-row">
              <p className="muted">Current CV: {basename(sourceDocuments.cv.file_path)} ({sourceDocuments.cv.parsed ? "parsed" : "uploaded, not parsed"})</p>
              <button
                aria-label={`Delete ${basename(sourceDocuments.cv.file_path)}`}
                className="icon-button danger"
                disabled={isAiPending}
                onClick={() =>
                  deleteUploadedDocument(
                    sourceDocuments.cv.file_path,
                    "cv",
                    basename(sourceDocuments.cv.file_path)
                  )
                }
                type="button"
              >
                x
              </button>
            </div>
          )}
          <label>
            Upload CV *
            <input type="file" accept=".pdf,.txt,.md" onChange={(event) => setCvFile(event.target.files?.[0] || null)} />
          </label>
          {cvFile && <p className="muted">Selected file: {cvFile.name}</p>}
          <div className="actions">
            <AiActionButton
              className="primary"
              disabled={isAiPending}
              isPending={pendingAction === "parse-cv"}
              label="Parse CV with AI"
              onClick={parseCv}
              pendingLabel="Parsing CV..."
            />
          </div>
        </section>

        <section className="panel">
          <SectionHeader title="2. Optional documents" summary={`${sourceDocuments.optional_documents?.length || 0} uploaded`} />
          {!!sourceDocuments.optional_documents?.length && (
            <>
              <strong>Uploaded optional documents</strong>
              {sourceDocuments.optional_documents.map((doc: ApiRecord, index: number) => (
                <div className="uploaded-document-row" key={`${doc.file_name}-${index}`}>
                  <p className="muted">{doc.file_name} - {doc.document_type}, {doc.parsed ? "parsed" : "not parsed"}</p>
                  <button
                    aria-label={`Delete ${doc.file_name}`}
                    className="icon-button danger"
                    disabled={isAiPending}
                    onClick={() =>
                      deleteUploadedDocument(
                        doc.file_path || "",
                        doc.document_type || "other",
                        doc.file_name || "document"
                      )
                    }
                    type="button"
                  >
                    x
                  </button>
                </div>
              ))}
            </>
          )}
          {[
            ["reference", "Upload references"],
            ["certificate", "Upload certificates"],
            ["other", "Upload other documents"]
          ].map(([documentType, label]) => (
            <label key={documentType}>
              {label}
              <input
                type="file"
                multiple
                accept=".pdf,.txt,.md,.docx"
                onChange={(event) =>
                  setOptionalFiles((current) => ({
                    ...current,
                    [documentType]: Array.from(event.target.files || [])
                  }))
                }
              />
            </label>
          ))}
          <div className="actions">
            <AiActionButton
              className="primary"
              disabled={isAiPending}
              isPending={pendingAction === "parse-optional-documents"}
              label="Parse optional documents with AI"
              onClick={parseOptionalDocuments}
              pendingLabel="Parsing optional documents..."
            />
          </div>
        </section>

        <section className="panel">
          <SectionHeader title="3. Extracted data review" summary={sourceDocuments.cv?.parsed ? "Ready for human review" : "Waiting for parsed CV"} />
          {!sourceDocuments.cv?.parsed && <StatusMessage type="info" text="Upload and parse a CV to populate these review fields." />}
          <h3>Identity</h3>
          <div className="grid">
            <label>First name *<input value={extracted.identity.first_name || ""} onChange={(event) => updateIdentity("first_name", event.target.value)} /></label>
            <label>Surname *<input value={extracted.identity.last_name || ""} onChange={(event) => updateIdentity("last_name", event.target.value)} /></label>
            <label>Gender *<select value={extracted.identity.gender || ""} onChange={(event) => updateIdentity("gender", event.target.value)}><option value="">Select gender</option>{genderOptions.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Email *<input value={extracted.identity.email || ""} onChange={(event) => updateIdentity("email", event.target.value)} /></label>
            <label>Phone *<input value={extracted.identity.phone || ""} onChange={(event) => updateIdentity("phone", event.target.value)} /></label>
            <label>Location<input value={extracted.identity.location || ""} onChange={(event) => updateIdentity("location", event.target.value)} /></label>
            <label>Street *<input value={extracted.identity.street_address || ""} onChange={(event) => updateIdentity("street_address", event.target.value)} /></label>
            <label>Street number *<input value={extracted.identity.street_number || ""} onChange={(event) => updateIdentity("street_number", event.target.value)} /></label>
            <label>Postal code *<input value={extracted.identity.postal_code || ""} onChange={(event) => updateIdentity("postal_code", event.target.value)} /></label>
            <label>City *<input value={extracted.identity.city || ""} onChange={(event) => updateIdentity("city", event.target.value)} /></label>
            <label>Country of residence *<input value={extracted.identity.country || ""} onChange={(event) => updateIdentity("country", event.target.value)} /></label>
            <label>Nationality *<input value={extracted.identity.nationality || ""} onChange={(event) => updateIdentity("nationality", event.target.value)} /></label>
            <label>LinkedIn URL<input value={extracted.identity.linkedin_url || ""} onChange={(event) => updateIdentity("linkedin_url", event.target.value)} /></label>
            <label>GitHub URL<input value={extracted.identity.github_url || ""} onChange={(event) => updateIdentity("github_url", event.target.value)} /></label>
            <label>Portfolio URL<input value={extracted.identity.portfolio_url || ""} onChange={(event) => updateIdentity("portfolio_url", event.target.value)} /></label>
          </div>
          <details open>
            <summary>Professional data</summary>
            <TextArea label="Work experience" value={blockTextFromItems(extracted.work_experience)} onChange={(value) => updateExtractedList("work_experience", value, true)} />
            <TextArea label="Education" value={textFromItems(extracted.education)} onChange={(value) => updateExtractedList("education", value)} />
            <TextArea label="Skills" value={textFromItems(extracted.skills)} onChange={(value) => updateExtractedList("skills", value)} />
            <TextArea label="Languages" value={textFromItems(extracted.languages)} onChange={(value) => updateExtractedList("languages", value)} />
            <TextArea label="Certifications" value={textFromItems(extracted.certifications)} onChange={(value) => updateExtractedList("certifications", value)} />
            <TextArea label="Projects" value={textFromItems(extracted.projects)} onChange={(value) => updateExtractedList("projects", value)} />
            <TextArea label="References" value={textFromItems(extracted.references)} onChange={(value) => updateExtractedList("references", value)} />
          </details>
          <div className="actions">
            <AiActionButton
              className="primary"
              isPending={pendingAction === "save-review"}
              label="Save CV review changes"
              onClick={saveReview}
              pendingLabel="Saving CV review..."
            />
          </div>
        </section>

        <section className="panel">
          <SectionHeader title="4. Optional job-search preferences" summary={`${(preferences.target_roles || []).length} target roles`} />
          <p className="muted">These fields can help future discovery and ranking, but they are not required to save a profile or prepare a known job application.</p>
          <TextArea label="Target roles" value={(preferences.target_roles || []).join("\n")} onChange={(value) => updatePreference("target_roles", linesFromText(value))} />
          <TextArea label="Target locations" value={(preferences.target_locations || []).join("\n")} onChange={(value) => updatePreference("target_locations", linesFromText(value))} />
          <CheckboxGroup title="Remote preference" options={remotePreference} values={preferences.remote_preference || []} onChange={(value) => updatePreference("remote_preference", value)} />
          <CheckboxGroup title="Employment type" options={employmentType} values={preferences.employment_type || []} onChange={(value) => updatePreference("employment_type", value)} />
          <CheckboxGroup title="Career level" options={careerLevel} values={preferences.seniority_level || []} onChange={(value) => updatePreference("seniority_level", value)} />
          <div className="grid">
            <label>Availability<input value={preferences.availability || ""} onChange={(event) => updatePreference("availability", event.target.value)} /></label>
            <label>Work authorization<select value={preferences.work_authorization || ""} onChange={(event) => updatePreference("work_authorization", event.target.value)}><option value=""></option>{workAuthorization.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Salary min (EUR / year)<input value={preferences.salary_min_eur ?? ""} onChange={(event) => updatePreference("salary_min_eur", optionalNumber(event.target.value))} /></label>
            <label>Salary max (EUR / year)<input value={preferences.salary_max_eur ?? ""} onChange={(event) => updatePreference("salary_max_eur", optionalNumber(event.target.value))} /></label>
          </div>
          <div className="actions">
            <AiActionButton
              className="primary"
              isPending={pendingAction === "save-preferences"}
              label="Save manual preferences"
              onClick={savePreferences}
              pendingLabel="Saving preferences..."
            />
          </div>
        </section>

      </fieldset>
    </>
  );
}
