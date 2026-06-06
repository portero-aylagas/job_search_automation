import { CSSProperties, useEffect, useState } from "react";
import karenEmojiImage from "../../../assets/ui/karen_emoji.png";
import { CandidateProfilePage } from "../features/candidateProfile/CandidateProfilePage";
import { JobIntakePage } from "../features/jobIntake/JobIntakePage";
import { JobsPage } from "../features/jobs/JobsPage";
import { KarenChatPanel } from "../features/karen/KarenChatPanel";
import { useKarenController } from "../features/karen/useKarenController";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { TrackerPage } from "../features/tracker/TrackerPage";
import { pages } from "./navigation";

function AppShell() {
  const [page, setPage] = useState("Candidate Profile");
  const karen = useKarenController({ page, setPage });

  useEffect(() => {
    let favicon = document.querySelector<HTMLLinkElement>("link[rel='icon']");
    if (!favicon) {
      favicon = document.createElement("link");
      favicon.rel = "icon";
      document.head.appendChild(favicon);
    }
    favicon.href = karenEmojiImage;
  }, []);

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
        className={`workspace-layout ${page === "Jobs" ? "with-karen" : ""}`}
        style={{ "--karen-panel-width": `${karen.panelProps.width}px` } as CSSProperties}
      >
        <main className="page">
          {page === "Candidate Profile" && (
            <CandidateProfilePage
              onRefreshComplete={karen.completeVisibleWorkflowRefresh}
              onWorkflowChange={karen.refreshKarenState}
              refreshScopes={karen.workflowRefresh.scopes}
              refreshSignal={karen.workflowRefresh.version}
            />
          )}
          {page === "Job Intake" && (
            <JobIntakePage
              onSaved={(jobId) => {
                karen.loadKarenJobs(jobId);
                setPage("Jobs");
              }}
            />
          )}
          {page === "Jobs" && (
            <JobsPage
              agent={karen.agent}
              onRefreshComplete={karen.completeVisibleWorkflowRefresh}
              onNavigateToIntake={() => setPage("Job Intake")}
              onSelectedJobChange={karen.syncKarenWithJobsSelection}
              onWorkflowChange={karen.refreshKarenState}
              refreshJobId={karen.workflowRefresh.jobId}
              refreshScopes={karen.workflowRefresh.scopes}
              refreshSignal={karen.workflowRefresh.version}
            />
          )}
          {page === "Tracker" && (
            <TrackerPage
              onRefreshComplete={karen.completeVisibleWorkflowRefresh}
              onWorkflowChange={karen.refreshKarenState}
              refreshScopes={karen.workflowRefresh.scopes}
              refreshSignal={karen.workflowRefresh.version}
            />
          )}
          {page === "Monitoring" && <MonitoringPage />}
        </main>
        {page === "Jobs" && <KarenChatPanel {...karen.panelProps} />}
      </div>
    </div>
  );
}

export default AppShell;
