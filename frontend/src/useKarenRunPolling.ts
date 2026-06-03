import { Dispatch, SetStateAction, useEffect, useState } from "react";
import { apiRequest, ApiRecord } from "./api";

type UseKarenRunPollingParams = {
  selectedJobId: string;
  sessionId?: string;
  setAgent: Dispatch<SetStateAction<ApiRecord | null>>;
  setStatus: (status: ApiRecord | null) => void;
  loadKarenJobs: (preferredJobId?: string, nextSessionId?: string) => void;
  refreshFromEvents: (events: ApiRecord[], fallbackJobId?: string) => void;
  refreshVisibleWorkflow: (jobId?: string, scopes?: string[]) => void;
};

export function useKarenRunPolling({
  selectedJobId,
  sessionId,
  setAgent,
  setStatus,
  loadKarenJobs,
  refreshFromEvents,
  refreshVisibleWorkflow
}: UseKarenRunPollingParams) {
  const [activeRunId, setActiveRunId] = useState("");
  const [activeRunStatus, setActiveRunStatus] = useState("");

  useEffect(() => {
    if (!activeRunId) return;
    let intervalId = 0;
    let cancelled = false;

    const pollKarenRun = async () => {
      try {
        const result = await apiRequest<ApiRecord>(`/api/agent/runs/${activeRunId}`);
        if (cancelled) return;
        const events = result.events || [];
        setActiveRunStatus(String(result.run?.status || ""));
        setAgent((currentAgent) => ({
          context: result.context || currentAgent?.context || {},
          state: result.state || currentAgent?.state || {},
          messages: result.messages || currentAgent?.messages || [],
          events,
          action_labels: result.action_labels || currentAgent?.action_labels || {}
        }));
        refreshFromEvents(events, result.context?.selected_job_id || selectedJobId);
        if (isTerminalKarenRunStatus(String(result.run?.status || ""))) {
          window.clearInterval(intervalId);
          setActiveRunId("");
          setActiveRunStatus("");
          const nextJobId = result.context?.selected_job_id || selectedJobId;
          loadKarenJobs(nextJobId, result.context?.session_id || sessionId);
          refreshVisibleWorkflow(nextJobId);
        }
      } catch (error) {
        if (!cancelled) {
          setStatus({ type: "error", text: error instanceof Error ? error.message : String(error) });
          window.clearInterval(intervalId);
          setActiveRunId("");
          setActiveRunStatus("");
        }
      }
    };

    void pollKarenRun();
    intervalId = window.setInterval(pollKarenRun, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeRunId]);

  function startKarenRun(runId: string, status = "running") {
    setActiveRunId(runId);
    setActiveRunStatus(status);
  }

  return {
    activeRunId,
    activeRunStatus,
    startKarenRun
  };
}

function isTerminalKarenRunStatus(status: string) {
  return ["completed", "blocked", "needs_input", "refused", "error"].includes(status);
}
