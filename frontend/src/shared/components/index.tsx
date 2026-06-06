import type { ButtonHTMLAttributes } from "react";
import type { ApiRecord } from "../types";
import { splitSelected, titleCase } from "../utils/format";

type AiActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  pendingLabel: string;
  isPending: boolean;
};

export function AiActionButton({
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

export function SectionHeader({ title, summary }: { title: string; summary?: string }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {summary && <span>{summary}</span>}
    </div>
  );
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`status-badge ${status}`}>{label || titleCase(status)}</span>;
}




export function TextArea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<textarea value={value || ""} onChange={(event) => onChange(event.target.value)} /></label>;
}

export function CheckboxGroup({ title, options, values, onChange }: { title: string; options: string[][]; values: string[]; onChange: (values: string[]) => void }) {
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

export function FillPlanInput({ row, value, onChange }: { row: ApiRecord; value: string; onChange: (value: string) => void }) {
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

export function Field({ label, value }: { label: string; value: any }) {
  return <div><strong>{label}</strong><p className="field-value">{value || "Not specified"}</p></div>;
}

export function List({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return <div><strong>{title}</strong>{values.map((value) => <p key={value}>- {value}</p>)}</div>;
}

export function StatusMessage({ type, text }: { type?: string; text?: string }) {
  if (!text) return null;
  return <div className={`message ${type || "info"}`}>{text}</div>;
}

export function Blockers({ title, blockers }: { title: string; blockers?: string[] }) {
  if (!blockers?.length) return null;
  return <div className="message warning"><strong>{title}</strong>{blockers.map((item) => <p key={item}>- {item}</p>)}</div>;
}

export function DataTable({ records }: { records: ApiRecord[] }) {
  if (!records.length) return <StatusMessage type="info" text="No tracker records found." />;
  const columns = Object.keys(records[0]);
  return <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{titleCase(column)}</th>)}</tr></thead><tbody>{records.map((record, index) => <tr key={record.job_id || index}>{columns.map((column) => <td key={column}>{String(record[column] ?? "")}</td>)}</tr>)}</tbody></table></div>;
}

export function DynamicDetails({ details }: { details: ApiRecord }) {
  const dynamic = details.dynamic_fields || [];
  return (
    <>
      {!!dynamic.length && <><strong>Additional Extracted Details</strong>{dynamic.map((field: ApiRecord, index: number) => <Field key={`${field.name}-${index}`} label={field.name || "Additional Detail"} value={field.value} />)}</>}
      {details.extraction_confidence && <Field label="Extraction Confidence" value={details.extraction_confidence} />}
      {details.apply_url_resolution && <><strong>Apply URL Resolution</strong>{["status", "confidence", "notes"].map((key) => <Field key={key} label={titleCase(key)} value={details.apply_url_resolution[key]} />)}</>}
    </>
  );
}

export function KeyRequirements({ requirements }: { requirements: ApiRecord }) {
  const items = [
    ...(requirements.required_documents || []).map((item: ApiRecord) => item.label),
    ...(requirements.upload_expectations || []).map((item: ApiRecord) => item.label),
    requirements.motivation_letter?.label,
    ...(requirements.consent_requirements || []).filter((item: ApiRecord) => item.required).map((item: ApiRecord) => item.label)
  ].filter(Boolean);
  return <List title="Key Requirements" values={Array.from(new Set(items))} />;
}

export function Traceability({ metadata }: { metadata: ApiRecord }) {
  const traceability = metadata.traceability;
  if (!traceability) return null;
  return <details><summary>Traceability</summary><List title="Source requirements" values={(traceability.source_requirements || []).map((item: ApiRecord) => `${item.label || item.evidence || "Requirement"} (confidence: ${item.confidence || "unknown"})`)} /><List title="Source experience" values={(traceability.source_experience_units || []).map((item: ApiRecord) => `${item.title || item.id || "Experience"}${item.organization ? ` / ${item.organization}` : ""}`)} /></details>;
}
