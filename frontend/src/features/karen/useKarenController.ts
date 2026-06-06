import { Dispatch, FormEvent, PointerEvent as ReactPointerEvent, SetStateAction, useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api";
import { eventRefreshScopes, fullWorkflowRefreshScopes, karenRefreshEventKey, shouldRefreshForKarenEvent, uniqueStrings, workflowPageHandlesRefresh } from "../../app/workflowRefresh";
import type { ApiRecord } from "../../shared/types";
import { runBusy } from "../../shared/utils/apiActions";
import { clampNumber, isActiveKarenRunStatus, karenActionTarget, karenPanelWidthKey, karenPanelWidthMax, karenPanelWidthMin, readKarenPanelWidth } from "./karenUtils";
import { useKarenRunPolling } from "./useKarenRunPolling";

type UseKarenControllerParams = {
  page: string;
  setPage: Dispatch<SetStateAction<string>>;
};

export function useKarenController({ page, setPage }: UseKarenControllerParams) {
  const [karenRecords, setKarenRecords] = useState<ApiRecord[]>([]);
  const [selectedKarenJobId, setSelectedKarenJobId] = useState("");
  const [agent, setAgent] = useState<ApiRecord | null>(null);
  const [karenMessage, setKarenMessage] = useState("");
  const [karenStatus, setKarenStatus] = useState<ApiRecord | null>(null);
  const [karenPanelWidth, setKarenPanelWidth] = useState(readKarenPanelWidth);
  const [isKarenSending, setIsKarenSending] = useState(false);
  const [isKarenMobileOpen, setIsKarenMobileOpen] = useState(false);
  const [workflowRefresh, setWorkflowRefresh] = useState({
    version: 0,
    jobId: "",
    scopes: fullWorkflowRefreshScopes
  });
  const [pendingKarenRefresh, setPendingKarenRefresh] = useState<ApiRecord | null>(null);
  const karenSendingRef = useRef(false);
  const seenRefreshEventIdsRef = useRef<Set<string>>(new Set());
  const sessionId = agent?.context?.session_id;
  const {
    activeRunStatus: activeKarenRunStatus,
    startKarenRun
  } = useKarenRunPolling({
    selectedJobId: selectedKarenJobId,
    sessionId,
    setAgent,
    setStatus: setKarenStatus,
    loadKarenJobs,
    refreshFromEvents: refreshFromKarenEvents,
    refreshVisibleWorkflow
  });
  const isKarenBusy = isKarenSending || isActiveKarenRunStatus(activeKarenRunStatus);

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

  function syncKarenWithJobsSelection(jobId: string) {
    if (jobId === selectedKarenJobId) return;
    setSelectedKarenJobId(jobId);
    loadAgent(jobId, sessionId);
  }

  function refreshVisibleWorkflow(jobId = "", scopes: string[] = fullWorkflowRefreshScopes) {
    setWorkflowRefresh((current) => ({
      version: current.version + 1,
      jobId,
      scopes: uniqueStrings(scopes)
    }));
  }

  function completeVisibleWorkflowRefresh() {
    if (!pendingKarenRefresh) return;
    refreshKarenState(pendingKarenRefresh.jobId, pendingKarenRefresh.sessionId);
    setPendingKarenRefresh(null);
  }

  useEffect(() => {
    loadKarenJobs("", "");
  }, []);

  useEffect(() => {
    if (!isKarenSending || page !== "Jobs") return;
    const pollKarenProgress = () => {
      loadAgent(selectedKarenJobId, sessionId);
    };
    const intervalId = window.setInterval(pollKarenProgress, 1000);
    return () => window.clearInterval(intervalId);
  }, [isKarenSending, page, selectedKarenJobId, sessionId]);

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
      if (result.run_id || result.run?.run_id) {
        seenRefreshEventIdsRef.current = new Set();
        startKarenRun(
          String(result.run_id || result.run.run_id),
          String(result.status || result.run?.status || "running")
        );
        return;
      }
      const executedActions = result.tool_result?.executed_actions || result.tool_result?.event_details?.executed_actions || [];
      if (result.tool_result?.status === "executed" || executedActions.length) {
        if (workflowPageHandlesRefresh(page)) {
          setPendingKarenRefresh({ jobId: nextJobId, sessionId: result.context?.session_id });
        } else {
          refreshKarenState(nextJobId, result.context?.session_id);
        }
        refreshVisibleWorkflow(nextJobId);
      } else {
        loadAgent(nextJobId, result.context?.session_id);
      }
    });
    karenSendingRef.current = false;
  }

  function refreshFromKarenEvents(events: ApiRecord[], fallbackJobId = "") {
    const refreshScopes = new Set<string>();
    let refreshJobId = fallbackJobId;

    for (const event of events) {
      if (!shouldRefreshForKarenEvent(event)) continue;
      const eventKey = karenRefreshEventKey(event);
      if (seenRefreshEventIdsRef.current.has(eventKey)) continue;
      seenRefreshEventIdsRef.current.add(eventKey);
      eventRefreshScopes(event).forEach((scope) => refreshScopes.add(scope));
      if (event.job_id) refreshJobId = String(event.job_id);
    }

    if (refreshScopes.size) {
      refreshVisibleWorkflow(refreshJobId, Array.from(refreshScopes));
    }
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

  return {
    agent,
    completeVisibleWorkflowRefresh,
    loadKarenJobs,
    refreshKarenState,
    syncKarenWithJobsSelection,
    workflowRefresh,
    panelProps: {
      agent,
      records: karenRecords,
      message: karenMessage,
      status: karenStatus,
      width: karenPanelWidth,
      isSending: isKarenBusy,
      isMobileOpen: isKarenMobileOpen,
      onMobileToggle: () => setIsKarenMobileOpen((current) => !current),
      onActionShortcut: navigateKarenAction,
      onMessageChange: setKarenMessage,
      onWidthChange: updateKarenPanelWidth,
      onResizeStart: startKarenPanelResize,
      onSendChat: sendKarenChat
    }
  };
}
