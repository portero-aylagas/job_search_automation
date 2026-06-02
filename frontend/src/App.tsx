import {
  ButtonHTMLAttributes,
  CSSProperties,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { apiRequest, ApiRecord, fileToPayload } from "./api";
import karenImage from "../../assets/karen.png";

const pages = ["Candidate Profile", "Job Intake", "Jobs", "Tracker", "Agent Karen"];
const careerLevel = [
  ["internship", "Internship"],
  ["working_student", "Working student"],
  ["trainee", "Trainee"],
  ["junior", "Junior"],
  ["entry_level", "Entry level"],
  ["mid_level", "Mid level"],
  ["senior", "Senior"],
  ["lead", "Lead"],
  ["principal", "Principal"],
  ["manager", "Manager"]
];
const remotePreference = [
  ["remote", "Remote"],
  ["hybrid", "Hybrid"],
  ["onsite", "On-site"]
];
const employmentType = [
  ["full_time", "Full-time"],
  ["part_time", "Part-time"],
  ["contract", "Contract"],
  ["freelance", "Freelance"]
];
const workAuthorization = [
  ["eu_authorized", "EU authorized"],
  ["eu_sponsorship_required", "EU sponsorship required"]
];
const genderOptions = ["Male", "Female", "Diverse"];
const karenPanelWidthKey = "karenPanelWidth";
const karenPanelWidthMin = 320;
const karenPanelWidthMax = 560;
const karenPanelWidthDefault = 380;

function App() {
  const [page, setPage] = useState("Candidate Profile");
  const [karenRecords, setKarenRecords] = useState<ApiRecord[]>([]);
  const [selectedKarenJobId, setSelectedKarenJobId] = useState("");
  const [agent, setAgent] = useState<ApiRecord | null>(null);
  const [karenMessage, setKarenMessage] = useState("");
  const [karenStatus, setKarenStatus] = useState<ApiRecord | null>(null);
  const [karenPanelWidth, setKarenPanelWidth] = useState(readKarenPanelWidth);
  const [isKarenSending, setIsKarenSending] = useState(false);
  const [isKarenMobileOpen, setIsKarenMobileOpen] = useState(false);
  const karenSendingRef = useRef(false);
  const sessionId = agent?.context?.session_id;

  useEffect(() => {
    let favicon = document.querySelector<HTMLLinkElement>("link[rel='icon']");
    if (!favicon) {
      favicon = document.createElement("link");
      favicon.rel = "icon";
      document.head.appendChild(favicon);
    }
    favicon.href = karenImage;
  }, []);

  function loadAgent(jobId = selectedKarenJobId, nextSessionId = sessionId) {
    const query = new URLSearchParams();
    if (jobId) query.set("selected_job_id", jobId);
    if (nextSessionId) query.set("session_id", nextSessionId);
    apiRequest<ApiRecord>(`/api/agent?${query.toString()}`)
      .then(setAgent)
      .catch((error) => setKarenStatus({ type: "error", text: error.message }));
  }

  function loadKarenJobs(preferredJobId = selectedKarenJobId, nextSessionId = sessionId) {
    apiRequest<ApiRecord>("/api/jobs")
      .then((payload) => {
        const records = payload.records || [];
        const nextJobId = records.some((record: ApiRecord) => record.job_id === preferredJobId)
          ? preferredJobId
          : records[0]?.job_id || "";
        setKarenRecords(records);
        setSelectedKarenJobId(nextJobId);
        loadAgent(nextJobId, nextSessionId);
      })
      .catch((error) => setKarenStatus({ type: "error", text: error.message }));
  }

  function refreshKarenState(preferredJobId = selectedKarenJobId, nextSessionId = sessionId) {
    loadKarenJobs(preferredJobId, nextSessionId);
  }

  useEffect(() => {
    loadKarenJobs("", "");
  }, []);

  async function sendKarenChat(event: FormEvent, overrideMessage?: string) {
    event.preventDefault();
    const outgoingMessage = (overrideMessage ?? karenMessage).trim();
    if (!outgoingMessage || karenSendingRef.current) return;
    karenSendingRef.current = true;
    await runBusy(setIsKarenSending, setKarenStatus, async () => {
      const result = await apiRequest<ApiRecord>("/api/agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message: outgoingMessage,
          selected_job_id: selectedKarenJobId,
          session_id: sessionId
        })
      });
      if (!overrideMessage) setKarenMessage("");
      const nextJobId = result.context?.selected_job_id || selectedKarenJobId;
      if (result.context?.selected_job_id) setSelectedKarenJobId(result.context.selected_job_id);
      loadAgent(nextJobId, result.context?.session_id);
    });
    karenSendingRef.current = false;
  }

  function selectKarenJob(jobId: string) {
    setSelectedKarenJobId(jobId);
    loadAgent(jobId, sessionId);
  }

  function navigateToWorkflowTarget(pageName: string, sectionId?: string) {
    setPage(pageName);
    if (!sectionId) return;
    window.setTimeout(() => {
      document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }

  function navigateKarenAction(actionName: string) {
    const target = karenActionTarget(actionName);
    if (!target) return;
    navigateToWorkflowTarget(target.page, target.sectionId);
    setIsKarenMobileOpen(false);
  }

  function updateKarenPanelWidth(width: number) {
    const nextWidth = clampNumber(width, karenPanelWidthMin, karenPanelWidthMax);
    setKarenPanelWidth(nextWidth);
    localStorage.setItem(karenPanelWidthKey, String(nextWidth));
  }

  function startKarenPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    document.body.classList.add("resizing-karen-panel");

    const resize = (resizeEvent: PointerEvent) => {
      updateKarenPanelWidth(window.innerWidth - resizeEvent.clientX);
    };
    const stopResize = () => {
      document.body.classList.remove("resizing-karen-panel");
      document.removeEventListener("pointermove", resize);
    };

    resize(event.nativeEvent);
    document.addEventListener("pointermove", resize);
    document.addEventListener("pointerup", stopResize, { once: true });
  }

  return (
    <div className="app-shell">
      <nav className="top-nav" aria-label="Navigate">
        {pages.map((name) => (
          <button
            key={name}
            className={`tab-button ${page === name ? "active" : ""}`}
            onClick={() => setPage(name)}
          >
            {name}
          </button>
        ))}
      </nav>
      <div
        className="workspace-layout"
        style={{ "--karen-panel-width": `${karenPanelWidth}px` } as CSSProperties}
      >
        <main className="page">
          {page === "Candidate Profile" && <CandidateProfilePage onWorkflowChange={refreshKarenState} />}
          {page === "Job Intake" && (
            <JobIntakePage
              onSaved={(jobId) => {
                loadKarenJobs(jobId);
                setPage("Jobs");
              }}
            />
          )}
          {page === "Jobs" && (
            <JobsPage
              onNavigateToIntake={() => setPage("Job Intake")}
              onWorkflowChange={refreshKarenState}
            />
          )}
          {page === "Tracker" && <TrackerPage onWorkflowChange={refreshKarenState} />}
          {page === "Agent Karen" && (
            <AgentKarenPage
              agent={agent}
              records={karenRecords}
              selectedJobId={selectedKarenJobId}
              status={karenStatus}
              onActionShortcut={navigateKarenAction}
            />
          )}
        </main>
        <KarenChatPanel
          agent={agent}
          records={karenRecords}
          selectedJobId={selectedKarenJobId}
          message={karenMessage}
          status={karenStatus}
          width={karenPanelWidth}
          isSending={isKarenSending}
          isMobileOpen={isKarenMobileOpen}
          onMobileToggle={() => setIsKarenMobileOpen((current) => !current)}
          onActionShortcut={navigateKarenAction}
          onMessageChange={setKarenMessage}
          onSelectJob={selectKarenJob}
          onWidthChange={updateKarenPanelWidth}
          onResizeStart={startKarenPanelResize}
          onSendChat={sendKarenChat}
        />
      </div>
    </div>
  );
}

function CandidateProfilePage({
  onWorkflowChange
}: {
  onWorkflowChange: (jobId?: string, nextSessionId?: string) => void;
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

  useEffect(() => {
    apiRequest<ApiRecord>("/api/candidate-profile")
      .then((payload) => setProfile(payload.profile))
      .catch((error) => setMessage({ type: "error", text: error.message }));
  }, []);

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
            <p className="muted">Current CV: {basename(sourceDocuments.cv.file_path)} ({sourceDocuments.cv.parsed ? "parsed" : "uploaded, not parsed"})</p>
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
                <p className="muted" key={`${doc.file_name}-${index}`}>{doc.file_name} - {doc.document_type}, {doc.parsed ? "parsed" : "not parsed"}</p>
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

function JobIntakePage({ onSaved }: { onSaved: (jobId: string) => void }) {
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

function JobsPage({
  onNavigateToIntake,
  onWorkflowChange
}: {
  onNavigateToIntake: () => void;
  onWorkflowChange: (jobId?: string, nextSessionId?: string) => void;
}) {
  const [records, setRecords] = useState<ApiRecord[]>([]);
  const [statusOptions, setStatusOptions] = useState<ApiRecord[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [workspace, setWorkspace] = useState<ApiRecord | null>(null);
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);

  function loadJobs() {
    apiRequest<ApiRecord>("/api/jobs").then((payload) => {
      setRecords(payload.records || []);
      setStatusOptions(payload.status_options || []);
      if (!selectedJobId && payload.records?.[0]) setSelectedJobId(payload.records[0].job_id);
    }).catch((error) => setMessage({ type: "error", text: error.message }));
  }

  useEffect(loadJobs, []);
  useEffect(() => {
    if (!selectedJobId) return;
    setLoadingWorkspace(true);
    apiRequest<ApiRecord>(`/api/jobs/${selectedJobId}/workspace`)
      .then(setWorkspace)
      .catch((error) => setMessage({ type: "error", text: error.message }))
      .finally(() => setLoadingWorkspace(false));
  }, [selectedJobId]);

  async function reloadWorkspace() {
    if (!selectedJobId) return;
    const [workspacePayload, jobsPayload] = await Promise.all([
      apiRequest<ApiRecord>(`/api/jobs/${selectedJobId}/workspace`),
      apiRequest<ApiRecord>("/api/jobs")
    ]);
    setWorkspace(workspacePayload);
    setRecords(jobsPayload.records || []);
    setStatusOptions(jobsPayload.status_options || []);
    onWorkflowChange(selectedJobId);
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
            <select value={selectedJobId} onChange={(event) => setSelectedJobId(event.target.value)}>
              {records.map((record) => <option key={record.job_id} value={record.job_id}>{record.company} / {record.title}</option>)}
            </select>
          </label>
          <div className="job-list" role="list">
            {records.map((record) => (
              <button
                className={`job-list-item ${record.job_id === selectedJobId ? "selected" : ""}`}
                key={record.job_id}
                onClick={() => setSelectedJobId(record.job_id)}
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

function JobSnapshot({ job }: { job: ApiRecord }) {
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

function RequirementsPanel({ workspace, setMessage, reload }: PanelProps) {
  const requirements = workspace.requirements;
  const [form, setForm] = useState<ApiRecord>(() => requirementsToForm(requirements));
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
            <label>Overall confidence<select value={form.confidence} onChange={(event) => setForm((current) => ({ ...current, confidence: event.target.value }))}>{["low", "medium", "high"].map((value) => <option key={value}>{value}</option>)}</select></label>
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
    (packageData?.artifacts || []).forEach((artifact: ApiRecord) => {
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
      await action(`/api/jobs/${workspace.job.id}/package/review`, "PUT", { edits_by_artifact_id: edits }, setMessage, reload);
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
              {orderArtifacts(packageData.artifacts || []).map((artifact: ApiRecord) => (
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
  const [values, setValues] = useState<ApiRecord>({});
  const [uploads, setUploads] = useState<ApiRecord>({});
  const [generating, setGenerating] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  useEffect(() => {
    const nextValues: ApiRecord = {};
    const nextUploads: ApiRecord = {};
    [...(review?.required_rows || []), ...(review?.optional_rows || [])].forEach((row: ApiRecord) => {
      nextValues[row.edit_key] = row.value || "";
    });
    (review?.upload_rows || []).forEach((row: ApiRecord) => {
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
    const edited_values: ApiRecord = {};
    const needs_answer_values_by_key: ApiRecord = {};
    const blocked_values_by_key: ApiRecord = {};
    [...(review?.required_rows || []), ...(review?.optional_rows || [])].forEach((row: ApiRecord) => {
      if (row.kind === "field") edited_values[row.edit_key] = values[row.edit_key] || "";
      if (row.kind === "needs") needs_answer_values_by_key[row.edit_key] = values[row.edit_key] || "";
      if (row.kind === "blocked") blocked_values_by_key[row.edit_key] = values[row.edit_key] || "";
    });
    await runBusy(setSavingReview, setMessage, async () => {
      await action(`/api/jobs/${workspace.job.id}/fill-plan/review`, "PUT", {
        edited_values,
        upload_paths_by_key: uploads,
        needs_answer_values_by_key,
        blocked_values_by_key
      }, setMessage, reload);
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
              {review.required_rows?.map((row: ApiRecord) => <FillPlanInput key={row.edit_key} row={row} value={values[row.edit_key] || ""} onChange={(value) => setValues((current) => ({ ...current, [row.edit_key]: value }))} />)}
            </div>
            <div className="workflow-subsection">
              <h3>Uploads Sent To Browser</h3>
              {!review.upload_rows?.length && <p className="muted">No uploads sent to browser.</p>}
              {review.upload_rows?.map((row: ApiRecord) => <label key={row.edit_key}>{row.label} file path<input value={uploads[row.edit_key] || ""} onChange={(event) => setUploads((current) => ({ ...current, [row.edit_key]: event.target.value }))} /></label>)}
            </div>
            <details><summary>Optional or unclear</summary>{!review.optional_rows?.length && <p className="muted">No optional or unclear fields.</p>}{review.optional_rows?.map((row: ApiRecord) => <FillPlanInput key={row.edit_key} row={row} value={values[row.edit_key] || ""} onChange={(value) => setValues((current) => ({ ...current, [row.edit_key]: value }))} />)}</details>
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

function TrackerPage({
  onWorkflowChange
}: {
  onWorkflowChange: (jobId?: string, nextSessionId?: string) => void;
}) {
  const [records, setRecords] = useState<ApiRecord[]>([]);
  const [statusOptions, setStatusOptions] = useState<ApiRecord[]>([]);
  const [statusFilters, setStatusFilters] = useState<ApiRecord[]>([]);
  const [message, setMessage] = useState<ApiRecord | null>(null);
  const [statusFilter, setStatusFilter] = useState("All");

  function loadTracker() {
    apiRequest<ApiRecord>("/api/tracker")
      .then((payload) => {
        setRecords(payload.records || []);
        setStatusOptions(payload.status_options || []);
        setStatusFilters(payload.status_filters || []);
      })
      .catch((error) => setMessage({ type: "error", text: error.message }));
  }

  useEffect(() => {
    loadTracker();
  }, []);

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
          />
        </>
      )}
    </>
  );
}

function AgentKarenPage({
  agent,
  records,
  selectedJobId,
  status,
  onActionShortcut
}: {
  agent: ApiRecord | null;
  records: ApiRecord[];
  selectedJobId: string;
  status: ApiRecord | null;
  onActionShortcut: (actionName: string) => void;
}) {
  const state = agent?.state || {};
  const selectedRecord = records.find((record) => record.job_id === selectedJobId);
  return (
    <>
      <div className="karen-header">
        <img src={karenImage} width="128" height="126" alt="Agent Karen" />
        <h1>Agent Karen</h1>
      </div>
      <StatusMessage type={status?.type} text={status?.text} />
      {!records.length && <StatusMessage type="info" text="No jobs have been added yet." />}
      <section className="panel">
        <h2>Karen Dashboard</h2>
        {selectedRecord && (
          <p className="muted">
            Selected job: {selectedRecord.company} / {selectedRecord.title}
          </p>
        )}
        <div className="grid three">
          <Field label="Job" value={state.selected_job_id || "None"} />
          <Field label="Gate" value={state.pending_gate || "None"} />
          <Field label="Actions" value={String(state.next_allowed_actions?.length || 0)} />
        </div>
        <Blockers title="Workflow blockers" blockers={state.blockers} />
        <Blockers title="Last workflow error" blockers={state.errors} />
        <details><summary>Workflow timeline</summary>{Object.entries(state.artifacts_present || {}).map(([label, present]) => <p key={label}>- {titleCase(label)}: {present ? "ready" : "missing"}</p>)}</details>
        {!!state.next_allowed_actions?.length && (
          <>
            <h3>Next Actions</h3>
            <div className="action-shortcuts">
              {state.next_allowed_actions.map((actionName: string) => (
                <KarenActionShortcut
                  actionName={actionName}
                  key={actionName}
                  label={agent?.action_labels?.[actionName] || titleCase(actionName)}
                  onActionShortcut={onActionShortcut}
                />
              ))}
            </div>
          </>
        )}
      </section>
    </>
  );
}

function KarenChatPanel({
  agent,
  records,
  selectedJobId,
  message,
  status,
  width,
  isSending,
  isMobileOpen,
  onMobileToggle,
  onActionShortcut,
  onMessageChange,
  onSelectJob,
  onWidthChange,
  onResizeStart,
  onSendChat
}: {
  agent: ApiRecord | null;
  records: ApiRecord[];
  selectedJobId: string;
  message: string;
  status: ApiRecord | null;
  width: number;
  isSending: boolean;
  isMobileOpen: boolean;
  onMobileToggle: () => void;
  onActionShortcut: (actionName: string) => void;
  onMessageChange: (message: string) => void;
  onSelectJob: (jobId: string) => void;
  onWidthChange: (width: number) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onSendChat: (event: FormEvent, overrideMessage?: string) => void;
}) {
  const state = agent?.state || {};
  const messages = agent?.messages || [];
  const blockers = [...(state.blockers || []), ...(state.errors || [])].filter(Boolean);
  const nextActions = state.next_allowed_actions || [];
  const chatLogRef = useRef<HTMLDivElement | null>(null);
  const latestMessage = messages[messages.length - 1];
  const quickPrompts = [
    "What is blocking this application?",
    "What should I do next?",
    "Summarize the selected job status."
  ];

  useEffect(() => {
    if (!messages.length) return;
    const chatLog = chatLogRef.current;
    if (!chatLog) return;
    if (typeof chatLog.scrollTo === "function") {
      chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: "smooth" });
      return;
    }
    chatLog.scrollTop = chatLog.scrollHeight;
  }, [messages.length, latestMessage?.content, latestMessage?.timestamp]);

  function resizeWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      onWidthChange(width + 20);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      onWidthChange(width - 20);
    }
  }

  function submitQuickPrompt(prompt: string) {
    const event = { preventDefault() {} } as FormEvent;
    onSendChat(event, prompt);
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <aside className={`karen-chat-panel ${isMobileOpen ? "mobile-open" : "mobile-closed"}`} aria-label="Karen chat">
      <button className="karen-mobile-toggle" onClick={onMobileToggle} type="button">
        {isMobileOpen ? "Close Karen" : "Open Karen"}
      </button>
      <div
        aria-label="Resize Karen panel"
        aria-orientation="vertical"
        aria-valuemax={karenPanelWidthMax}
        aria-valuemin={karenPanelWidthMin}
        aria-valuenow={width}
        className="karen-resize-handle"
        onKeyDown={resizeWithKeyboard}
        onPointerDown={onResizeStart}
        role="separator"
        tabIndex={0}
      />
      <fieldset aria-busy={isSending} className="ai-blocking-surface karen-chat-controls" disabled={isSending}>
        <div className="karen-panel-top">
          <div className="karen-panel-header">
            <img src={karenImage} width="56" height="56" alt="Agent Karen" />
            <div>
              <h2>Karen Chat</h2>
              <p className="muted">Workflow assistant</p>
            </div>
          </div>
          <StatusMessage type={status?.type} text={status?.text} />
          {!records.length && <StatusMessage type="info" text="No jobs have been added yet." />}
          {!!records.length && (
            <label>
              Job
              <select value={selectedJobId} onChange={(event) => onSelectJob(event.target.value)}>
                {records.map((record) => (
                  <option key={record.job_id} value={record.job_id}>
                    {record.company} / {record.title}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="karen-context-summary" aria-label="Karen workflow summary">
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
              <strong>{nextActionLabel(nextActions, agent?.action_labels)}</strong>
            </div>
          </div>
          <div className="quick-prompts" aria-label="Karen quick prompts">
            {nextActions.map((actionName: string) => {
              const target = karenActionTarget(actionName);
              if (!target) return null;
              return (
                <button
                  className="quick-prompt action"
                  disabled={isSending || !records.length}
                  key={actionName}
                  onClick={() => onActionShortcut(actionName)}
                  type="button"
                >
                  {agent?.action_labels?.[actionName] || titleCase(actionName)}
                </button>
              );
            })}
            {quickPrompts.map((prompt) => (
              <button
                className="quick-prompt"
                disabled={isSending || !records.length}
                key={prompt}
                onClick={() => submitQuickPrompt(prompt)}
                type="button"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
        <div aria-label="Karen transcript" className="chat-log" ref={chatLogRef} role="log">
          {!messages.length && (
            <div className="chat-empty">
              <strong>No messages yet.</strong>
              <p>Ask about blockers, the next gate, or what is ready for the selected job.</p>
            </div>
          )}
          {messages.map((item: ApiRecord, index: number) => (
            <div className={`chat-message ${item.role === "user" ? "user" : "assistant"}`} key={`${item.timestamp}-${index}`}>
              <div className="chat-message-meta">
                <strong>{item.role === "user" ? "You" : "Karen"}</strong>
                {item.timestamp && <time dateTime={item.timestamp}>{formatTimestamp(item.timestamp)}</time>}
              </div>
              <p>{item.content}</p>
              {!!item.actions?.length && (
                <div className="chat-action-badges" aria-label="Message actions">
                  {item.actions.map((actionName: string) => (
                    <KarenActionShortcut
                      actionName={actionName}
                      key={actionName}
                      label={agent?.action_labels?.[actionName] || titleCase(actionName)}
                      onActionShortcut={onActionShortcut}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        <form onSubmit={onSendChat} className="karen-chat-form">
          <div className="karen-composer">
            <textarea
              aria-label="Ask Karen"
              disabled={isSending}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask Karen"
              rows={2}
              value={message}
              onChange={(event) => onMessageChange(event.target.value)}
            />
            <button
              aria-busy={isSending}
              aria-label={isSending ? "Asking Karen..." : "Ask Karen"}
              className="karen-send-button"
              disabled={isSending || !message.trim()}
              title={isSending ? "Asking Karen..." : "Ask Karen"}
            >
              <span aria-hidden="true" className={isSending ? "send-spinner" : "send-icon"} />
            </button>
          </div>
        </form>
      </fieldset>
    </aside>
  );
}

type PanelProps = {
  workspace: ApiRecord;
  setMessage: (message: ApiRecord | null) => void;
  reload: () => Promise<void> | void;
};

type AiActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  pendingLabel: string;
  isPending: boolean;
};

function AiActionButton({
  className,
  disabled,
  isPending,
  label,
  pendingLabel,
  type = "button",
  ...props
}: AiActionButtonProps) {
  const currentLabel = isPending ? pendingLabel : label;
  return (
    <button
      {...props}
      aria-busy={isPending ? true : undefined}
      className={`ai-action-button ${className || ""}`.trim()}
      disabled={disabled || isPending}
      type={type}
    >
      <span className="ai-button-content">
        {isPending && <span aria-hidden="true" className="ai-button-spinner" />}
        <span>{currentLabel}</span>
      </span>
      <span aria-hidden="true" className="ai-button-sizer">
        {pendingLabel}
      </span>
    </button>
  );
}

function SectionHeader({ title, summary }: { title: string; summary?: string }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {summary && <span>{summary}</span>}
    </div>
  );
}

function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`status-badge ${status}`}>{label || titleCase(status)}</span>;
}

function WorkflowStepper({ workspace }: { workspace: ApiRecord }) {
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

function KarenActionShortcut({
  actionName,
  label,
  onActionShortcut
}: {
  actionName: string;
  label: string;
  onActionShortcut: (actionName: string) => void;
}) {
  if (!karenActionTarget(actionName)) {
    return <span className="action-badge">{label}</span>;
  }
  return (
    <button className="action-badge button" onClick={() => onActionShortcut(actionName)} type="button">
      {label}
    </button>
  );
}

function TrackerTable({
  records,
  statusOptions,
  onStatusChange
}: {
  records: ApiRecord[];
  statusOptions: ApiRecord[];
  onStatusChange: (jobId: string, status: string) => void;
}) {
  if (!records.length) return <StatusMessage type="info" text="No tracker records match this filter." />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {["Company", "Title", "Status", "Next action", "Blockers", "Last updated", "Links"].map((column) => (
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TextArea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<textarea value={value || ""} onChange={(event) => onChange(event.target.value)} /></label>;
}

function CheckboxGroup({ title, options, values, onChange }: { title: string; options: string[][]; values: string[]; onChange: (values: string[]) => void }) {
  return (
    <div>
      <h3>{title}</h3>
      <div className="check-grid">
        {options.map(([value, label]) => (
          <label className="check-row" key={value}>
            <input type="checkbox" checked={values.includes(value)} onChange={(event) => onChange(event.target.checked ? [...values, value] : values.filter((item) => item !== value))} />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}

function FillPlanInput({ row, value, onChange }: { row: ApiRecord; value: string; onChange: (value: string) => void }) {
  const inputType = String(row.input_type || "").toLowerCase();
  const options = row.options || [];
  return (
    <div>
      {inputType === "checkbox" && <label className="check-row"><input type="checkbox" checked={["true", "yes", "ja", "1", "checked"].includes(value.toLowerCase())} onChange={(event) => onChange(event.target.checked ? "true" : "false")} />{row.label}</label>}
      {["checkbox_group", "multiselect", "multi_select"].includes(inputType) && !!options.length && <label>{row.label}<select multiple value={splitSelected(value)} onChange={(event) => onChange(Array.from(event.currentTarget.selectedOptions).map((option) => option.value).join("; "))}>{options.map((option: string) => <option key={option}>{option}</option>)}</select></label>}
      {["select", "radio"].includes(inputType) && !!options.length && <label>{row.label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value=""></option>{options.concat(options.includes(value) || !value ? [] : [value]).map((option: string) => <option key={option}>{option}</option>)}</select></label>}
      {!(inputType === "checkbox" || ((["checkbox_group", "multiselect", "multi_select", "select", "radio"].includes(inputType)) && !!options.length)) && <label>{row.label}<input value={value} onChange={(event) => onChange(event.target.value)} /></label>}
      {row.reason && <p className="muted">{row.reason}</p>}
    </div>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return <div><strong>{label}</strong><p className="field-value">{value || "Not specified"}</p></div>;
}

function List({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return <div><strong>{title}</strong>{values.map((value) => <p key={value}>- {value}</p>)}</div>;
}

function StatusMessage({ type, text }: { type?: string; text?: string }) {
  if (!text) return null;
  return <div className={`message ${type || "info"}`}>{text}</div>;
}

function Blockers({ title, blockers }: { title: string; blockers?: string[] }) {
  if (!blockers?.length) return null;
  return <div className="message warning"><strong>{title}</strong>{blockers.map((item) => <p key={item}>- {item}</p>)}</div>;
}

function DataTable({ records }: { records: ApiRecord[] }) {
  if (!records.length) return <StatusMessage type="info" text="No tracker records found." />;
  const columns = Object.keys(records[0]);
  return <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{titleCase(column)}</th>)}</tr></thead><tbody>{records.map((record, index) => <tr key={record.job_id || index}>{columns.map((column) => <td key={column}>{String(record[column] ?? "")}</td>)}</tr>)}</tbody></table></div>;
}

function DynamicDetails({ details }: { details: ApiRecord }) {
  const dynamic = details.dynamic_fields || [];
  return (
    <>
      {!!dynamic.length && <><strong>Additional Extracted Details</strong>{dynamic.map((field: ApiRecord, index: number) => <Field key={`${field.name}-${index}`} label={field.name || "Additional Detail"} value={field.value} />)}</>}
      {details.extraction_confidence && <Field label="Extraction Confidence" value={details.extraction_confidence} />}
      {details.apply_url_resolution && <><strong>Apply URL Resolution</strong>{["status", "confidence", "notes"].map((key) => <Field key={key} label={titleCase(key)} value={details.apply_url_resolution[key]} />)}</>}
    </>
  );
}

function KeyRequirements({ requirements }: { requirements: ApiRecord }) {
  const items = [
    ...(requirements.required_documents || []).map((item: ApiRecord) => item.label),
    ...(requirements.upload_expectations || []).map((item: ApiRecord) => item.label),
    requirements.motivation_letter?.label,
    ...(requirements.consent_requirements || []).filter((item: ApiRecord) => item.required).map((item: ApiRecord) => item.label)
  ].filter(Boolean);
  return <List title="Key Requirements" values={Array.from(new Set(items))} />;
}

function Traceability({ metadata }: { metadata: ApiRecord }) {
  const traceability = metadata.traceability;
  if (!traceability) return null;
  return <details><summary>Traceability</summary><List title="Source requirements" values={(traceability.source_requirements || []).map((item: ApiRecord) => `${item.label || item.evidence || "Requirement"} (confidence: ${item.confidence || "unknown"})`)} /><List title="Source experience" values={(traceability.source_experience_units || []).map((item: ApiRecord) => `${item.title || item.id || "Experience"}${item.organization ? ` / ${item.organization}` : ""}`)} /></details>;
}

async function saveProfileDraft(path: string, profile: ApiRecord, setProfile: (profile: ApiRecord) => void, setMessage: (message: ApiRecord | null) => void) {
  const result = await apiRequest<ApiRecord>(path, {
    method: "PUT",
    body: JSON.stringify({ profile })
  });
  setProfile(result.profile);
  setMessage({ type: "success", text: result.message || `Saved to ${result.saved_path}.` });
}

async function action(
  path: string,
  method: string,
  body: ApiRecord,
  setMessage: (message: ApiRecord | null) => void,
  reload: () => Promise<void> | void
) {
  try {
    const result = await apiRequest<ApiRecord>(path, { method, body: JSON.stringify(body) });
    setMessage({ type: "success", text: result.message || "Saved." });
    await reload();
  } catch (error) {
    setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
  }
}

async function runBusy(setBusy: (value: boolean) => void, setMessage: (message: ApiRecord | null) => void, work: () => Promise<void>) {
  setBusy(true);
  try {
    await work();
  } catch (error) {
    setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
  } finally {
    setBusy(false);
  }
}

function textFields(labels: string[], keys: string[], form: ApiRecord, setForm: (updater: (current: ApiRecord) => ApiRecord) => void) {
  return labels.map((label, index) => {
    const key = keys[index];
    return <label key={key}>{label}<input value={form[key] || ""} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} /></label>;
  });
}

function updateNested(current: ApiRecord | null, path: string[], value: any) {
  const clone = structuredClone(current || {});
  let target = clone;
  path.slice(0, -1).forEach((key) => {
    target[key] = target[key] || {};
    target = target[key];
  });
  target[path[path.length - 1]] = value;
  return clone;
}

function updateDynamicField(index: number, value: string, setForm: (updater: (current: ApiRecord) => ApiRecord) => void) {
  setForm((current) => {
    const dynamic = [...(current.dynamic_fields || [])];
    dynamic[index] = { ...dynamic[index], value };
    return { ...current, dynamic_fields: dynamic };
  });
}

function requirementsToForm(requirements: ApiRecord | null) {
  if (!requirements) return {};
  return {
    job_preserving: !!requirements.job_preserving,
    confidence: requirements.confidence || "medium",
    blocked_reason: requirements.blocked_reason || "",
    required_documents_text: formatFindings(requirements.required_documents),
    upload_expectations_text: formatFindings(requirements.upload_expectations),
    motivation_label: requirements.motivation_letter?.label || "",
    motivation_required: !!requirements.motivation_letter?.required,
    profile_fields_text: formatFields(requirements.profile_fields),
    screening_questions_text: formatQuestions(requirements.screening_questions),
    custom_form_fields_text: formatFields(requirements.custom_form_fields),
    consent_requirements_text: formatFindings(requirements.consent_requirements),
    privacy_login_ats_gates_text: formatFindings(requirements.privacy_login_ats_gates),
    deadlines_text: formatFindings(requirements.deadlines),
    contact_or_fallback_text: formatFindings(requirements.contact_or_fallback),
    missing_or_uncertain_text: textFromItems(requirements.missing_or_uncertain)
  };
}

function formatFindings(items: ApiRecord[] = []) {
  return items.map((item) => `- [${item.required ? "required" : "optional"}] ${item.label}`).join("\n");
}

function formatQuestions(items: ApiRecord[] = []) {
  return items.map((item) => `- [${item.required ? "required" : "optional"}] ${item.question} | ${item.input_type || "text"}`).join("\n");
}

function formatFields(items: ApiRecord[] = []) {
  return items.map((item) => {
    const suffix = ` | ${item.input_type || "text"}${item.options?.length ? ` | ${item.options.join("; ")}` : ""}`;
    return `- [${item.required ? "required" : "optional"}] ${item.label}${suffix}`;
  }).join("\n");
}

function textFromItems(items: string[] = []) {
  return items.filter((item) => item?.trim()).map((item) => `- ${item.trim()}`).join("\n");
}

function blockTextFromItems(items: string[] = []) {
  return items.map((item) => {
    const lines = item.split(/\r?\n/).map((line) => line.replace(/^[-*•\s]+/, "").trim()).filter(Boolean);
    if (lines.length <= 1) return lines[0] || "";
    return `${lines[0]}\n${lines.slice(1).map((line) => `- ${line}`).join("\n")}`;
  }).filter(Boolean).join("\n\n");
}

function linesFromText(value: string) {
  return value.split(/\r?\n/).map((line) => line.replace(/^[-*•\s]+/, "").trim()).filter(Boolean);
}

function blocksFromText(value: string) {
  return value.replace(/\r\n/g, "\n").split("\n\n").map((block) => linesFromText(block).join("\n")).filter(Boolean);
}

function optionalNumber(value: string) {
  const normalized = value.trim().replace(/[.,]/g, "");
  return normalized ? Number(normalized) : null;
}

function readKarenPanelWidth() {
  const savedWidth = Number(localStorage.getItem(karenPanelWidthKey));
  return clampNumber(savedWidth || karenPanelWidthDefault, karenPanelWidthMin, karenPanelWidthMax);
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function splitSelected(value: string) {
  return value.includes(";") ? value.split(";").map((item) => item.trim()).filter(Boolean) : value ? [value] : [];
}

function orderArtifacts(artifacts: ApiRecord[]) {
  return [...artifacts].sort((a, b) => Number(!isCoverLetter(a)) - Number(!isCoverLetter(b)));
}

function isCoverLetter(artifact: ApiRecord) {
  return artifact.type === "cover_letter" || String(artifact.label || "").toLowerCase().includes("cover letter");
}

function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function nextActionLabel(actions: string[] = [], labels: ApiRecord = {}) {
  if (!actions.length) return "None";
  return labels[actions[0]] || titleCase(actions[0]);
}

function profileStatus(workspace: ApiRecord) {
  const blockers = allWorkspaceBlockers(workspace).filter((item) => /profile|candidate|cv/i.test(item));
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  return { status: "complete", labelText: "Complete" };
}

function jobStatus(workspace: ApiRecord) {
  if (!workspace.job) return { status: "missing", labelText: "Missing" };
  if (!workspace.job.apply_url) return { status: "needs-review", labelText: "Needs review" };
  return { status: "complete", labelText: "Complete" };
}

function requirementsStatus(workspace: ApiRecord) {
  const requirements = workspace.requirements;
  if (!requirements) return { status: "missing", labelText: "Missing" };
  if (requirements.blocked_reason) return { status: "blocked", labelText: "Blocked" };
  if (requirements.confidence === "low") return { status: "low-confidence", labelText: "Low confidence" };
  if (requirements.review_status === "reviewed") return { status: "complete", labelText: "Complete" };
  return { status: "needs-review", labelText: "Needs review" };
}

function packageStatus(workspace: ApiRecord) {
  const blockers = workspace.package_blockers || [];
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  if (!workspace.package) return { status: "missing", labelText: "Missing" };
  if (["approved", "reviewed", "complete"].includes(workspace.package.status || workspace.package.review_status)) {
    return { status: "complete", labelText: "Complete" };
  }
  return { status: "needs-review", labelText: "Needs review" };
}

function fillPlanStatus(workspace: ApiRecord) {
  const blockers = workspace.fill_plan_generation_blockers || [];
  if (blockers.length) return { status: "blocked", labelText: "Blocked" };
  if (!workspace.fill_plan) return { status: "missing", labelText: "Missing" };
  if (workspace.fill_plan.review_status === "reviewed") return { status: "complete", labelText: "Complete" };
  return { status: "needs-review", labelText: "Needs review" };
}

function applyStatus(workspace: ApiRecord) {
  if (workspace.apply_blockers?.length) return { status: "blocked", labelText: "Blocked" };
  if (workspace.job?.status === "applied") return { status: "complete", labelText: "Complete" };
  return { status: "ready", labelText: "Ready" };
}

function reviewSummary(status?: string, confidence?: string) {
  const statusText = status ? titleCase(status) : "Needs review";
  return confidence ? `${statusText}, ${confidence} confidence` : statusText;
}

function allWorkspaceBlockers(workspace: ApiRecord) {
  return [
    ...(workspace.package_blockers || []),
    ...(workspace.fill_plan_generation_blockers || []),
    ...(workspace.apply_blockers || [])
  ].filter(Boolean);
}

function jobBlockerCount(record: ApiRecord, workspace: ApiRecord | null) {
  if (workspace) return allWorkspaceBlockers(workspace).length;
  return Number(record.blocker_count ?? record.blockers?.length ?? 0);
}

function nextWorkspaceAction(record: ApiRecord, workspace: ApiRecord | null) {
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

function trackerStatusMeta(status: string | undefined, options: ApiRecord[]) {
  const value = status || "new";
  return options.find((option) => option.value === value) || {
    value,
    label: titleCase(value),
    badge: "missing",
    user_editable: false
  };
}

function trackerStatusLabel(status: string | undefined, options: ApiRecord[]) {
  return trackerStatusMeta(status, options).label;
}

function trackerStatusBadge(status: string | undefined, options: ApiRecord[]) {
  return trackerStatusMeta(status, options).badge || "missing";
}

function karenActionTarget(actionName: string) {
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

function formatDateTime(value?: string) {
  if (!value) return "Not tracked";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default App;
