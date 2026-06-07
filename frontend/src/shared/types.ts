import type { ApiRecord } from "../api";

export type { ApiRecord };

export type ConfidenceLevel = "low" | "medium" | "high";

export type ReviewStatus = "draft" | "reviewed";

export type ApplicationArtifactStatus =
  | "draft"
  | "needs_review"
  | "approved"
  | "rejected"
  | "regenerated"
  | "manually_edited";

export type KarenWorkflowRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "blocked"
  | "needs_input"
  | "refused"
  | "error";

export type KarenActionLabels = Record<string, string>;

export interface TrackerStatusOption extends ApiRecord {
  value: string;
  label: string;
  badge: string;
  user_editable?: boolean;
}

export interface JobIndexRecord extends ApiRecord {
  job_id: string;
  title: string;
  company: string;
  status?: string;
  blockers?: string[];
  blocker_count?: number;
  next_allowed_actions?: string[];
  action_labels?: KarenActionLabels;
  next_action?: string;
  next_action_label?: string;
}

export interface JobsIndexPayload extends ApiRecord {
  records: JobIndexRecord[];
  status_options: TrackerStatusOption[];
}

export interface JobListingPayload extends ApiRecord {
  id: string;
  title: string;
  company: string;
  source_url: string;
  retrieval_mode: string;
  source_job_id?: string | null;
  location?: string | null;
  remote_policy?: string | null;
  apply_url?: string | null;
  description?: string | null;
  requirements: string[];
  responsibilities: string[];
  nice_to_have_skills: string[];
  salary?: string | null;
  posted_date?: string | null;
  job_details: ApiRecord;
}

export interface ApplicationRequirementFinding extends ApiRecord {
  label: string;
  required: boolean;
  evidence: string;
  confidence: ConfidenceLevel;
  constraints: string[];
}

export interface ApplicationScreeningQuestion extends ApiRecord {
  question: string;
  required: boolean;
  input_type: string;
  evidence: string;
  confidence: ConfidenceLevel;
}

export interface ApplicationFormField extends ApiRecord {
  name: string;
  label: string;
  required: boolean;
  input_type: string;
  options: string[];
  evidence: string;
  confidence: ConfidenceLevel;
}

export interface ApplicationRequirementsPayload extends ApiRecord {
  job_id: string;
  apply_url: string;
  source_url: string;
  status: "discovered" | "blocked";
  review_status: ReviewStatus;
  blocked_reason?: string | null;
  job_preserving: boolean;
  required_documents: ApplicationRequirementFinding[];
  upload_expectations: ApplicationRequirementFinding[];
  screening_questions: ApplicationScreeningQuestion[];
  custom_form_fields: ApplicationFormField[];
  profile_fields: ApplicationFormField[];
  motivation_letter?: ApplicationRequirementFinding | null;
  consent_requirements: ApplicationRequirementFinding[];
  privacy_login_ats_gates: ApplicationRequirementFinding[];
  deadlines: ApplicationRequirementFinding[];
  contact_or_fallback: ApplicationRequirementFinding[];
  missing_or_uncertain: string[];
  source_evidence: string[];
  confidence: ConfidenceLevel;
}

export interface ApplicationRequirementsReviewRequest extends ApiRecord {
  job_preserving: boolean;
  confidence: ConfidenceLevel;
  blocked_reason: string;
  required_documents_text: string;
  upload_expectations_text: string;
  motivation_label: string;
  motivation_required: boolean;
  profile_fields_text: string;
  screening_questions_text: string;
  custom_form_fields_text: string;
  consent_requirements_text: string;
  privacy_login_ats_gates_text: string;
  deadlines_text: string;
  contact_or_fallback_text: string;
  missing_or_uncertain_text: string;
}

export interface ApplicationArtifactPayload extends ApiRecord {
  id: string;
  type: string;
  label: string;
  required: boolean;
  status: ApplicationArtifactStatus;
  content: string;
  source_prompt?: string | null;
  source_requirement?: string | null;
  metadata: ApiRecord;
}

export interface ApplicationPackagePayload extends ApiRecord {
  job_id: string;
  status: ApplicationArtifactStatus;
  artifacts: ApplicationArtifactPayload[];
  missing_information: string[];
  selected_experience_units: string[];
  generation_notes: string[];
}

export interface ApplicationPackageSummary extends ApiRecord {
  status: ApplicationArtifactStatus;
  artifact_count: number;
  missing_information: string[];
  selected_experience_units: string[];
  generation_notes: string[];
}

export interface ApplicationPackageReviewRequest extends ApiRecord {
  edits_by_artifact_id: Record<string, string>;
}

export interface ApplicationFillFieldPayload extends ApiRecord {
  label: string;
  required: boolean;
  input_type: string;
  options: string[];
  source: string;
  confidence: ConfidenceLevel;
}

export interface ApplicationFillPlanPayload extends ApiRecord {
  job_id: string;
  apply_url: string;
  review_status: ReviewStatus;
  source_fingerprints: Record<string, string>;
  source_metadata: ApiRecord;
  field_values: ApplicationFillFieldPayload[];
  upload_files: ApplicationFillFieldPayload[];
  needs_answer_fields: ApplicationFillFieldPayload[];
  blocked_fields: ApplicationFillFieldPayload[];
  submit_guard_labels: string[];
}

export interface ApplicationFillPlanReviewRow extends ApiRecord {
  kind: "field" | "needs" | "blocked";
  edit_key: string;
  label: string;
  value: string;
  required: boolean;
  input_type: string;
  options: string[];
  reason: string;
  source: string;
  confidence: ConfidenceLevel;
}

export interface ApplicationFillPlanUploadRow extends ApiRecord {
  edit_key: string;
  label: string;
  file_path: string;
  document_type: string;
  required: boolean;
  source: string;
  confidence: ConfidenceLevel;
}

export interface ApplicationFillPlanReviewPayload extends ApiRecord {
  required_rows: ApplicationFillPlanReviewRow[];
  optional_rows: ApplicationFillPlanReviewRow[];
  upload_rows: ApplicationFillPlanUploadRow[];
}

export interface ApplicationFillPlanReviewRequest extends ApiRecord {
  edited_values: Record<string, string>;
  upload_paths_by_key: Record<string, string>;
  needs_answer_values_by_key: Record<string, string>;
  blocked_values_by_key: Record<string, string>;
}

export interface BrowserUseSessionPayload extends ApiRecord {
  pid: number;
  url: string;
  log_path?: string;
}

export interface JobWorkspacePayload extends ApiRecord {
  job: JobListingPayload;
  requirements: ApplicationRequirementsPayload | null;
  package: ApplicationPackagePayload | null;
  package_summary: ApplicationPackageSummary | null;
  fill_plan: ApplicationFillPlanPayload | null;
  fill_plan_review: ApplicationFillPlanReviewPayload | null;
  ai_quality_counters: ApiRecord;
  package_blockers: string[];
  fill_plan_generation_blockers: string[];
  apply_blockers: string[];
  active_browser_use_session: BrowserUseSessionPayload | null;
  browser_use_runner_count: number;
}

export interface KarenContextPayload extends ApiRecord {
  session_id: string;
  selected_job_id?: string | null;
}

export interface KarenWorkflowStatePayload extends ApiRecord {
  session_id: string;
  selected_job_id?: string | null;
  artifacts_present: Record<string, boolean>;
  blockers: string[];
  next_allowed_actions: string[];
  pending_gate?: string | null;
  errors: string[];
  last_user_intent?: string | null;
}

export interface KarenChatMessagePayload extends ApiRecord {
  timestamp: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  job_id?: string | null;
  proposed_actions?: string[];
  actions?: string[];
  executed_action?: string | null;
}

export interface KarenEventPayload extends ApiRecord {
  timestamp: string;
  created_at: string;
  event_type: string;
  session_id: string;
  job_id?: string | null;
  run_id?: string | null;
  action: string;
  label: string;
  result: string;
  status: string;
  message: string;
  blockers: string[];
  route_hint?: string | null;
  refresh_scopes: string[];
  next_allowed_actions: string[];
  metadata: ApiRecord;
  details: ApiRecord;
}

export interface KarenWorkflowRunPayload extends ApiRecord {
  run_id: string;
  session_id: string;
  job_id?: string | null;
  status: KarenWorkflowRunStatus;
  current_action?: string | null;
  started_at: string;
  finished_at?: string | null;
  final_message: string;
}

export interface KarenAgentPayload extends ApiRecord {
  context: KarenContextPayload;
  state: KarenWorkflowStatePayload;
  messages: KarenChatMessagePayload[];
  events: KarenEventPayload[];
  action_labels: KarenActionLabels;
}

export interface KarenChatResponse extends ApiRecord {
  context: KarenContextPayload;
  intent: ApiRecord | null;
  tool_result: ApiRecord | null;
  run?: KarenWorkflowRunPayload;
  run_id?: string;
  status?: KarenWorkflowRunStatus;
  reused_run?: boolean;
}

export interface KarenRunProgressPayload extends KarenAgentPayload {
  run: KarenWorkflowRunPayload;
}
