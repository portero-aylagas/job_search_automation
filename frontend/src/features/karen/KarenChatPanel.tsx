import { FormEvent, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, useEffect, useRef } from "react";
import karenChatImage from "../../../../assets/ui/karen_office.png";
import karenWorkingImage from "../../../../assets/ui/karen_working.gif";
import { StatusMessage } from "../../shared/components";
import type { ApiRecord, JobIndexRecord, KarenActionLabels, KarenAgentPayload, KarenChatMessagePayload, KarenEventPayload } from "../../shared/types";
import { formatTimestamp, titleCase } from "../../shared/utils/format";
import { formatKarenBlockedEvent, formatKarenIntent, isBlockedKarenEvent, karenActionTarget, karenPanelWidthMax, karenPanelWidthMin, karenProgressSteps, latestWorkflowRunId, progressStepSymbol } from "./karenUtils";

export function KarenChatPanel({
  agent,
  records,
  message,
  status,
  width,
  isSending,
  isMobileOpen,
  onMobileToggle,
  onActionShortcut,
  onMessageChange,
  onWidthChange,
  onResizeStart,
  onSendChat
}: {
  agent: KarenAgentPayload | null;
  records: JobIndexRecord[];
  message: string;
  status: ApiRecord | null;
  width: number;
  isSending: boolean;
  isMobileOpen: boolean;
  onMobileToggle: () => void;
  onActionShortcut: (actionName: string) => void;
  onMessageChange: (message: string) => void;
  onWidthChange: (width: number) => void;
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onSendChat: (event: FormEvent, overrideMessage?: string) => void;
}) {
  const messages = agent?.messages || [];
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
            <img
              src={isSending ? karenWorkingImage : karenChatImage}
              width="112"
              height="112"
              alt="Agent Karen"
            />
            <div>
              <h2>Karen Chat</h2>
              <p className="muted">Workflow assistant</p>
            </div>
          </div>
          <StatusMessage type={status?.type} text={status?.text} />
          {!records.length && <StatusMessage type="info" text="No jobs have been added yet." />}
          <KarenProgress
            actionLabels={agent?.action_labels || {}}
            events={agent?.events || []}
            isActive={isSending}
          />
          <div className="quick-prompts" aria-label="Karen quick prompts">
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
          {messages.map((item: KarenChatMessagePayload, index: number) => (
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

function KarenProgress({
  actionLabels,
  events,
  isActive
}: {
  actionLabels: KarenActionLabels;
  events: KarenEventPayload[];
  isActive: boolean;
}) {
  const latestRunId = latestWorkflowRunId(events);
  const runEvents = latestRunId
    ? events.filter((event) => (event.run_id || event.details?.workflow_run_id) === latestRunId)
    : events;
  const intentEvent = [...runEvents].reverse().find((event) => event.action === "karen_workflow_intent");
  const runStatusEvent = [...runEvents]
    .reverse()
    .find((event) => event.action === "karen_workflow_run");
  const steps = karenProgressSteps(runEvents, actionLabels);
  const currentStep = [...steps].reverse().find((step) => step.status === "running");
  const blockedStep = [...steps].reverse().find((step) => ["blocked", "needs_input", "refused", "error"].includes(step.status));
  const waitingEvent = runStatusEvent && ["needs_input", "waiting_for_review"].includes(String(runStatusEvent.status || runStatusEvent.result))
    ? runStatusEvent
    : null;
  const blockedEvent = [...runEvents]
    .reverse()
    .find((event) => isBlockedKarenEvent(event) && event !== waitingEvent);
  const completedSteps = steps.filter((step) => step.status === "completed");
  const nextAllowedActions = Array.isArray(runStatusEvent?.next_allowed_actions)
    ? runStatusEvent.next_allowed_actions
    : Array.isArray(runStatusEvent?.details?.next_allowed_actions)
      ? runStatusEvent.details.next_allowed_actions
      : [];
  const heading = blockedStep
    ? `Stopped at: ${blockedStep.label}`
    : currentStep
      ? `Karen is working on: ${currentStep.label}`
      : waitingEvent
        ? "Waiting for workflow review"
      : isActive
        ? "Karen is working"
        : "Latest Karen progress";

  if (!isActive && !intentEvent && !steps.length && !blockedEvent) {
    return null;
  }

  return (
    <section className="karen-progress" aria-label="Karen workflow progress">
      <div className="karen-progress-heading">
        <span className={`karen-progress-dot ${isActive ? "active" : ""}`} aria-hidden="true" />
        <strong>{heading}</strong>
      </div>
      {intentEvent && (
        <KarenProgressRow
          label="Understood"
          value={formatKarenIntent(intentEvent)}
        />
      )}
      {!!steps.length && (
        <div className="karen-progress-steps" aria-label="Karen action history">
          {steps.map((step, index) => (
            <div className={`karen-progress-step ${step.status}`} key={`${step.action}-${index}`}>
              <span aria-hidden="true">{progressStepSymbol(step.status)}</span>
              <strong>{step.label}</strong>
            </div>
          ))}
        </div>
      )}
      {!!completedSteps.length && (
        <KarenProgressRow label="Completed" value={completedSteps.map((step) => step.label).join(", ")} />
      )}
      {waitingEvent && (
        <KarenProgressRow
          label="Waiting for"
          value={waitingEvent.message || waitingEvent.details?.planner_message || "Review the current workflow state."}
        />
      )}
      {!!nextAllowedActions.length && (
        <KarenProgressRow
          label="Next allowed"
          value={nextAllowedActions.map((action) => actionLabels[action] || titleCase(String(action))).join(", ")}
        />
      )}
      {blockedEvent && (
        <KarenProgressRow
          label={blockedStep ? "Blocked" : "Blocked/Needs input"}
          value={formatKarenBlockedEvent(blockedEvent, actionLabels)}
        />
      )}
    </section>
  );
}

function KarenProgressRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="karen-progress-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
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
