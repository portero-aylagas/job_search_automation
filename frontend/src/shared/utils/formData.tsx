import type { ApiRecord, ApplicationFormField, ApplicationRequirementFinding, ApplicationRequirementsPayload, ApplicationRequirementsReviewRequest, ApplicationScreeningQuestion } from "../types";

export function textFields(labels: string[], keys: string[], form: ApiRecord, setForm: (updater: (current: ApiRecord) => ApiRecord) => void) {
  return labels.map((label, index) => {
    const key = keys[index];
    return <label key={key}>{label}<input value={form[key] || ""} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} /></label>;
  });
}

export function updateNested(current: ApiRecord | null, path: string[], value: any) {
  const clone = structuredClone(current || {});
  let target = clone;
  path.slice(0, -1).forEach((key) => {
    target[key] = target[key] || {};
    target = target[key];
  });
  target[path[path.length - 1]] = value;
  return clone;
}

export function updateDynamicField(index: number, value: string, setForm: (updater: (current: ApiRecord) => ApiRecord) => void) {
  setForm((current) => {
    const dynamic = [...(current.dynamic_fields || [])];
    dynamic[index] = { ...dynamic[index], value };
    return { ...current, dynamic_fields: dynamic };
  });
}

export function requirementsToForm(requirements: ApplicationRequirementsPayload | null): ApplicationRequirementsReviewRequest {
  if (!requirements) {
    return {
      job_preserving: false,
      confidence: "medium",
      blocked_reason: "",
      required_documents_text: "",
      upload_expectations_text: "",
      motivation_label: "",
      motivation_required: false,
      profile_fields_text: "",
      screening_questions_text: "",
      custom_form_fields_text: "",
      consent_requirements_text: "",
      privacy_login_ats_gates_text: "",
      deadlines_text: "",
      contact_or_fallback_text: "",
      missing_or_uncertain_text: ""
    };
  }
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

function formatFindings(items: ApplicationRequirementFinding[] = []) {
  return items.map((item) => `- [${item.required ? "required" : "optional"}] ${item.label}`).join("\n");
}

function formatQuestions(items: ApplicationScreeningQuestion[] = []) {
  return items.map((item) => `- [${item.required ? "required" : "optional"}] ${item.question} | ${item.input_type || "text"}`).join("\n");
}

function formatFields(items: ApplicationFormField[] = []) {
  return items.map((item) => {
    const suffix = ` | ${item.input_type || "text"}${item.options?.length ? ` | ${item.options.join("; ")}` : ""}`;
    return `- [${item.required ? "required" : "optional"}] ${item.label}${suffix}`;
  }).join("\n");
}

export function textFromItems(items: string[] = []) {
  return items.filter((item) => item?.trim()).map((item) => `- ${item.trim()}`).join("\n");
}

export function blockTextFromItems(items: string[] = []) {
  return items.map((item) => {
    const lines = item.split(/\r?\n/).map((line) => line.replace(/^[-*•\s]+/, "").trim()).filter(Boolean);
    if (lines.length <= 1) return lines[0] || "";
    return `${lines[0]}\n${lines.slice(1).map((line) => `- ${line}`).join("\n")}`;
  }).filter(Boolean).join("\n\n");
}

export function linesFromText(value: string) {
  return value.split(/\r?\n/).map((line) => line.replace(/^[-*•\s]+/, "").trim()).filter(Boolean);
}

export function blocksFromText(value: string) {
  return value.replace(/\r\n/g, "\n").split("\n\n").map((block) => linesFromText(block).join("\n")).filter(Boolean);
}

export function optionalNumber(value: string) {
  const normalized = value.trim().replace(/[.,]/g, "");
  return normalized ? Number(normalized) : null;
}

