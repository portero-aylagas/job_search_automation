import { apiRequest } from "../../api";
import type { ApiRecord } from "../types";

export async function saveProfileDraft(path: string, profile: ApiRecord, setProfile: (profile: ApiRecord) => void, setMessage: (message: ApiRecord | null) => void) {
  const result = await apiRequest<ApiRecord>(path, {
    method: "PUT",
    body: JSON.stringify({ profile })
  });
  setProfile(result.profile);
  setMessage({ type: "success", text: result.message || `Saved to ${result.saved_path}.` });
}

export async function action(
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

export async function runBusy(setBusy: (value: boolean) => void, setMessage: (message: ApiRecord | null) => void, work: () => Promise<void>) {
  setBusy(true);
  try {
    await work();
  } catch (error) {
    setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
  } finally {
    setBusy(false);
  }
}

