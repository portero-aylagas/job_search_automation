import type { ApiRecord, ApplicationArtifactPayload } from "../types";

export function splitSelected(value: string) {
  return value.includes(";") ? value.split(";").map((item) => item.trim()).filter(Boolean) : value ? [value] : [];
}

export function orderArtifacts(artifacts: ApplicationArtifactPayload[]) {
  return [...artifacts].sort((a, b) => Number(!isCoverLetter(a)) - Number(!isCoverLetter(b)));
}

export function isCoverLetter(artifact: ApplicationArtifactPayload) {
  return artifact.type === "cover_letter" || String(artifact.label || "").toLowerCase().includes("cover letter");
}

export function basename(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

export function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}


export function formatInteger(value: any) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "0";
  return Math.round(number).toLocaleString();
}

export function formatCost(value: any) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "$0.00";
  return number.toLocaleString([], { style: "currency", currency: "USD", maximumFractionDigits: 4 });
}

export function formatPercent(value: any) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "0%";
  return `${(number * 100).toFixed(number > 0 && number < 0.01 ? 2 : 1)}%`;
}

export function formatLatency(value: any) {
  if (value === null || value === undefined || value === "") return "Not tracked";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number.toFixed(number >= 10 ? 1 : 2)}s`;
}

export function formatDateTime(value?: string) {
  if (!value) return "Not tracked";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
