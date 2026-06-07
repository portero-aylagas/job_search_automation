export type ApiRecord = Record<string, any>;

const DEFAULT_DEV_API_BASE = "http://127.0.0.1:8001";

function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (configured) {
    return configured;
  }
  return import.meta.env.DEV ? DEFAULT_DEV_API_BASE : "";
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : {};
  if (!response.ok) {
    const detail = payload.detail || "Request failed.";
    const message = typeof detail === "string"
      ? detail
      : detail.message || JSON.stringify(detail);
    throw new Error(message);
  }
  if (!contentType.includes("application/json")) {
    throw new Error("API returned a non-JSON response. Check that the FastAPI server is running on 127.0.0.1:8001.");
  }
  return payload as T;
}

export async function fileToPayload(file: File, documentType = "other") {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return {
    filename: file.name,
    content_base64: btoa(binary),
    document_type: documentType
  };
}
