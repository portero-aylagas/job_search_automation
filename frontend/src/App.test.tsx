import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { apiRequest } from "./api";
import type { ApiRecord } from "./api";

type MockResponse = {
  status?: number;
  body?: unknown;
  contentType?: string;
};

describe("apiRequest", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("returns JSON success payloads", async () => {
    mockFetch(() => ({ body: { ok: true } }));

    await expect(apiRequest("/api/health")).resolves.toEqual({ ok: true });
  });

  it("surfaces JSON error details", async () => {
    mockFetch(() => ({ status: 400, body: { detail: "Bad request" } }));

    await expect(apiRequest("/api/fail")).rejects.toThrow("Bad request");
  });

  it("rejects non-JSON success responses", async () => {
    mockFetch(() => ({ body: "ok", contentType: "text/plain" }));

    await expect(apiRequest("/api/html")).rejects.toThrow("non-JSON response");
  });
});

describe("App workflow pages", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("loads Candidate Profile fields and surfaces API save errors", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile") && !init?.method) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/candidate-profile/review-changes")) {
        return { status: 400, body: { detail: "Email must be valid." } };
      }
      return { body: { records: [] } };
    });

    render(<App />);

    expect(await screen.findByDisplayValue("Taylor")).toBeInTheDocument();
    expect(screen.getByLabelText(/Email/)).toHaveValue("taylor@example.com");
    await userEvent.clear(screen.getByLabelText(/Email/));
    await userEvent.type(screen.getByLabelText(/Email/), "bad-email");
    await userEvent.click(screen.getByRole("button", { name: "Save CV review changes" }));

    expect(await screen.findByText("Email must be valid.")).toBeInTheDocument();
  });

  it("blocks Candidate Profile edits while CV parsing is running", async () => {
    let resolveParse: (value: MockResponse) => void = () => undefined;
    const pendingParse = new Promise<MockResponse>((resolve) => {
      resolveParse = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/candidate-profile/parse-cv")) {
        return pendingParse;
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [] } };
      }
      return { body: {} };
    });

    render(<App />);

    const cvInput = await screen.findByLabelText("Upload CV *");
    await userEvent.upload(cvInput, new File(["CV"], "cv.txt", { type: "text/plain" }));
    await userEvent.click(screen.getByRole("button", { name: "Parse CV with AI" }));

    expect(screen.getByRole("button", { name: "Parsing CV..." })).toBeDisabled();
    expect(screen.getByLabelText(/Email/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save CV review changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save manual preferences" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save profile" })).not.toBeInTheDocument();
    resolveParse({ body: { profile: candidateProfile(), message: "Parsed CV." } });
    expect(await screen.findByRole("button", { name: "Parse CV with AI" })).toBeEnabled();
  });

  it("deletes the uploaded CV from the Candidate Profile UI", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let currentProfile = candidateProfile();
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: currentProfile, options: {} } };
      }
      if (url.endsWith("/api/candidate-profile/document")) {
        currentProfile = candidateProfileWithoutCv();
        return {
          body: {
            profile: currentProfile,
            message: "Uploaded document deleted."
          }
        };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [] } };
      }
      return { body: {} };
    });

    render(<App />);

    expect(await screen.findByText(/Current CV: cv\.pdf/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete cv.pdf" }));

    expect(await screen.findByText("Uploaded document deleted.")).toBeInTheDocument();
    expect(screen.queryByText(/Current CV: cv\.pdf/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/First name/)).toHaveValue("");
  });

  it("deletes one uploaded optional document from the Candidate Profile UI", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let currentProfile = candidateProfileWithReferenceUploads();
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: currentProfile, options: {} } };
      }
      if (url.endsWith("/api/candidate-profile/document")) {
        currentProfile = candidateProfileWithoutReferences();
        return {
          body: {
            profile: currentProfile,
            message: "Uploaded document deleted."
          }
        };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [] } };
      }
      return { body: {} };
    });

    render(<App />);

    expect(await screen.findByText(/manager-reference\.pdf - reference, parsed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete manager-reference.pdf" }));

    expect(await screen.findByText("Uploaded document deleted.")).toBeInTheDocument();
    expect(screen.queryByText(/manager-reference\.pdf - reference, parsed/)).not.toBeInTheDocument();
    expect(screen.getByText(/cert\.pdf - certificate, parsed/)).toBeInTheDocument();
    expect(screen.getByLabelText("References")).toHaveValue("");
  });

  it("extracts Job Intake data, saves reviewed edits, and navigates to Jobs", async () => {
    const saveBodies: unknown[] = [];
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/job-intake/extract")) {
        return { body: jobExtraction() };
      }
      if (url.endsWith("/api/job-intake/save")) {
        saveBodies.push(JSON.parse(String(init?.body)));
        return { body: { message: "Added job.", job: normalizedJob() } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [] } };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Job Intake" }));
    await userEvent.type(screen.getByLabelText("Job URL"), "https://example.com/jobs/1");
    await userEvent.click(screen.getByRole("button", { name: "Extract application data with AI" }));

    expect(await screen.findByDisplayValue("Automation Engineer")).toBeInTheDocument();
    expect(screen.getByLabelText("Department")).toHaveValue("Platform");
    await userEvent.clear(screen.getByLabelText("Department"));
    await userEvent.type(screen.getByLabelText("Department"), "Reliability");
    await userEvent.click(screen.getByRole("button", { name: "Add To Application Workflow" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Jobs" })).toBeInTheDocument());
    expect(saveBodies).toHaveLength(1);
    expect((saveBodies[0] as any).dynamic_fields[0].value).toBe("Reliability");
  });

  it("shows pending feedback while Job Intake extraction is running", async () => {
    let resolveExtraction: (value: MockResponse) => void = () => undefined;
    const pendingExtraction = new Promise<MockResponse>((resolve) => {
      resolveExtraction = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/job-intake/extract")) {
        return pendingExtraction;
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [] } };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Job Intake" }));
    await userEvent.type(screen.getByLabelText("Job URL"), "https://example.com/jobs/1");
    await userEvent.click(screen.getByRole("button", { name: "Extract application data with AI" }));

    const pendingButton = screen.getByRole("button", { name: "Extracting application data..." });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    expect(screen.getByLabelText("Job URL")).toBeDisabled();
    resolveExtraction({ body: jobExtraction() });
    expect(await screen.findByRole("button", { name: "Extract application data with AI" })).toBeEnabled();
  });

  it("shows Jobs blockers and enables Apply only when review gates are complete", async () => {
    const workspaces = [blockedWorkspace(), readyWorkspace()];
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()], status_options: trackerStatusOptions() } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: workspaces.shift() || readyWorkspace() };
      }
      return { body: { message: "ok" } };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));

    expect(
      await screen.findAllByText((text) =>
        text.includes("Discover application requirements for this apply URL.")
      )
    ).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Apply to job with AI" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Discover requirements from apply URL with AI" }));

    expect(await screen.findByText("Ready summary")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply to job with AI" })).toBeEnabled();
  });

  it("shows the workflow stepper and switches selected job details", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord(), jobRecord2()] } };
      }
      if (url.includes("/api/jobs/job-2/workspace")) {
        return { body: readyWorkspace2() };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: blockedWorkspace() };
      }
      return { body: agentState(1) };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));

    expect(await screen.findByRole("list", { name: "Selected job workflow steps" })).toHaveTextContent("Requirements");
    expect(screen.getByRole("button", { name: /Automation Engineer/ })).toHaveClass("selected");
    await userEvent.click(screen.getByRole("button", { name: /Data Analyst/ }));

    expect(await screen.findByRole("heading", { name: "Example Analytics / Data Analyst" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Data Analyst/ })).toHaveClass("selected");
  });

  it("shows Not interested status wording and separate job management controls", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return {
          body: {
            records: [{ ...jobRecord(), status: "rejected_by_user" }],
            status_options: trackerStatusOptions()
          }
        };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: blockedWorkspace() };
      }
      return { body: agentState(1) };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));

    expect(await screen.findAllByText("Not interested")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Remove from active jobs" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Permanently delete job data" })).toBeInTheDocument();
  });

  it("shows pending feedback while requirements discovery is running", async () => {
    let resolveDiscovery: (value: MockResponse) => void = () => undefined;
    const pendingDiscovery = new Promise<MockResponse>((resolve) => {
      resolveDiscovery = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: blockedWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/requirements/discover")) {
        return pendingDiscovery;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Discover requirements from apply URL with AI" }));

    const pendingButton = screen.getByRole("button", { name: "Discovering requirements..." });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    resolveDiscovery({ body: { message: "Discovered requirements." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Discover requirements from apply URL with AI" })).toBeEnabled()
    );
  });

  it("blocks requirements review controls while requirements refresh is running", async () => {
    let resolveDiscovery: (value: MockResponse) => void = () => undefined;
    const pendingDiscovery = new Promise<MockResponse>((resolve) => {
      resolveDiscovery = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/requirements/discover")) {
        return pendingDiscovery;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Refresh requirements from apply URL with AI" }));

    expect(screen.getByRole("button", { name: "Refreshing requirements..." })).toBeDisabled();
    expect(screen.getByLabelText("Apply page matches this selected job")).toBeDisabled();
    expect(screen.getByLabelText("Overall confidence")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save requirements review" })).toBeDisabled();
    resolveDiscovery({ body: { message: "Refreshed requirements." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Refresh requirements from apply URL with AI" })).toBeEnabled()
    );
  });

  it("shows pending feedback while package generation is running", async () => {
    let resolvePackage: (value: MockResponse) => void = () => undefined;
    const pendingPackage = new Promise<MockResponse>((resolve) => {
      resolvePackage = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: packageReadyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/package/generate")) {
        return pendingPackage;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generate application package with AI" }));

    const pendingButton = screen.getByRole("button", { name: "Generating application package..." });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    resolvePackage({ body: { message: "Generated package." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Generate application package with AI" })).toBeEnabled()
    );
  });

  it("blocks package review controls while package regeneration is running", async () => {
    let resolvePackage: (value: MockResponse) => void = () => undefined;
    const pendingPackage = new Promise<MockResponse>((resolve) => {
      resolvePackage = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/package/generate")) {
        return pendingPackage;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Regenerate application package with AI" }));

    expect(screen.getByRole("button", { name: "Regenerating application package..." })).toBeDisabled();
    expect(screen.getByLabelText("Application Summary content")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save package review" })).toBeDisabled();
    resolvePackage({ body: { message: "Regenerated package." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Regenerate application package with AI" })).toBeEnabled()
    );
  });

  it("shows pending feedback and prevents repeat package review saves", async () => {
    let reviewCalls = 0;
    let resolveReview: (value: MockResponse) => void = () => undefined;
    const pendingReview = new Promise<MockResponse>((resolve) => {
      resolveReview = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/package/review")) {
        reviewCalls += 1;
        return pendingReview;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    const saveButton = await screen.findByRole("button", { name: "Save package review" });
    await userEvent.click(saveButton);
    fireEvent.click(saveButton);

    expect(screen.getByRole("button", { name: "Saving package review..." })).toBeDisabled();
    expect(reviewCalls).toBe(1);
    resolveReview({ body: { message: "Saved package review." } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save package review" })).toBeEnabled());
  });

  it("shows pending feedback while exporting the cover letter", async () => {
    let resolveExport: (value: MockResponse) => void = () => undefined;
    const pendingExport = new Promise<MockResponse>((resolve) => {
      resolveExport = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: coverLetterWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/package/export-cover-letter")) {
        return pendingExport;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Export cover letter PDF" }));

    expect(screen.getByRole("button", { name: "Exporting cover letter..." })).toBeDisabled();
    resolveExport({ body: { message: "Exported cover letter." } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Export cover letter PDF" })).toBeEnabled());
  });

  it("shows pending feedback while fill-plan generation is running", async () => {
    let resolveFillPlan: (value: MockResponse) => void = () => undefined;
    const pendingFillPlan = new Promise<MockResponse>((resolve) => {
      resolveFillPlan = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: fillPlanReadyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/fill-plan/generate")) {
        return pendingFillPlan;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generate fill plan with AI" }));

    const pendingButton = screen.getByRole("button", { name: "Generating fill plan..." });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    resolveFillPlan({ body: { message: "Generated fill plan." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Generate fill plan with AI" })).toBeEnabled()
    );
  });

  it("blocks fill-plan review controls while fill-plan refresh is running", async () => {
    let resolveFillPlan: (value: MockResponse) => void = () => undefined;
    const pendingFillPlan = new Promise<MockResponse>((resolve) => {
      resolveFillPlan = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/fill-plan/generate")) {
        return pendingFillPlan;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Refresh fill plan with AI" }));

    expect(screen.getByRole("button", { name: "Refreshing fill plan..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save fill plan review" })).toBeDisabled();
    resolveFillPlan({ body: { message: "Refreshed fill plan." } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Refresh fill plan with AI" })).toBeEnabled()
    );
  });

  it("shows pending feedback while saving fill-plan review", async () => {
    let resolveReview: (value: MockResponse) => void = () => undefined;
    const pendingReview = new Promise<MockResponse>((resolve) => {
      resolveReview = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/fill-plan/review")) {
        return pendingReview;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save fill plan review" }));

    expect(screen.getByRole("button", { name: "Saving fill plan review..." })).toBeDisabled();
    resolveReview({ body: { message: "Saved fill plan review." } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save fill plan review" })).toBeEnabled());
  });

  it("shows shared pending feedback while Apply starts", async () => {
    let resolveApply: (value: MockResponse) => void = () => undefined;
    const pendingApply = new Promise<MockResponse>((resolve) => {
      resolveApply = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: readyWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/apply")) {
        return pendingApply;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Apply to job with AI" }));

    const pendingButton = screen.getByRole("button", { name: "Starting AI apply assistance..." });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Stop Browser Use Session" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Kill All Browser Use Processes" })).toBeDisabled();
    resolveApply({ body: { message: "Started Browser Use apply agent." } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply to job with AI" })).toBeEnabled());
  });

  it("refreshes Karen workflow summary after fill plan review without a new chat turn", async () => {
    let fillPlanReviewed = false;
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()], status_options: trackerStatusOptions() } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: fillPlanReviewed ? readyWorkspace() : fillPlanReviewWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/fill-plan/review")) {
        fillPlanReviewed = true;
        return { body: { message: "Saved fill plan review." } };
      }
      if (url.includes("/api/agent")) {
        return { body: agentFillPlanState(fillPlanReviewed) };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));

    expect((await screen.findAllByText("Approve fill plan")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Karen workflow summary")).toHaveTextContent("Blockers1");

    await userEvent.click(screen.getByRole("button", { name: "Save fill plan review" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Prepare apply assistance" })).toBeInTheDocument()
    );
    expect(screen.getByLabelText("Karen workflow summary")).toHaveTextContent("Blockers0");
    expect(screen.queryByText("Approve fill plan")).not.toBeInTheDocument();
  });

  it("shows pending feedback for browser process controls", async () => {
    let resolveStop: (value: MockResponse) => void = () => undefined;
    const pendingStop = new Promise<MockResponse>((resolve) => {
      resolveStop = resolve;
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: browserActiveWorkspace() };
      }
      if (url.includes("/api/jobs/job-1/browser/stop-session")) {
        return pendingStop;
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop Browser Use Session" }));

    expect(screen.getByRole("button", { name: "Stopping Browser Use Session..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Kill All Browser Use Processes" })).toBeDisabled();
    resolveStop({ body: { message: "Stopped Browser Use session." } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop Browser Use Session" })).toBeEnabled());
  });

  it("shows tracker curated columns and filters", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.endsWith("/api/tracker")) {
        return {
          body: {
            records: [
              jobRecord(),
              { ...jobRecord2(), job_id: "job-3", company: "Draft Labs", status: "application_draft" },
              { ...jobRecord2(), status: "rejected", blocker_count: 2 }
            ],
            status_options: trackerStatusOptions(),
            status_filters: trackerStatusFilters()
          }
        };
      }
      if (url.includes("/api/tracker/job-3/status")) {
        return {
          body: {
            record: { ...jobRecord2(), job_id: "job-3", company: "Draft Labs", status: "interview" },
            status_options: trackerStatusOptions(),
            status_filters: trackerStatusFilters(),
            message: "Tracker status updated."
          }
        };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Tracker" }));

    expect(await screen.findByRole("columnheader", { name: "Company" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Retrieval Mode" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Application Draft" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Application Draft" }));

    expect(screen.getByText("Draft Labs")).toBeInTheDocument();
    expect(screen.queryByText("Example Co")).not.toBeInTheDocument();
    expect(screen.queryByText("Example Analytics")).not.toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByLabelText("Status for Draft Labs / Data Analyst"),
      "interview"
    );

    expect(await screen.findByText("Tracker status updated.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Interview / Offer" }));

    expect(screen.getByText("Draft Labs")).toBeInTheDocument();
    expect(screen.getAllByText("Interview").length).toBeGreaterThan(1);
    expect(screen.getByLabelText("Status for Draft Labs / Data Analyst")).toHaveValue("interview");

    await userEvent.click(screen.getByRole("button", { name: "New" }));

    expect(screen.getByText("Example Co")).toBeInTheDocument();
    expect(screen.queryByText("Draft Labs")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Closed" }));

    expect(screen.getByText("Example Analytics")).toBeInTheDocument();
    expect(screen.queryByText("Example Co")).not.toBeInTheDocument();
  });

  it("deletes a job from the tracker after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const deleteCalls: string[] = [];
    mockFetch((url, options) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.endsWith("/api/tracker")) {
        return {
          body: {
            records: [jobRecord()],
            status_options: trackerStatusOptions(),
            status_filters: trackerStatusFilters()
          }
        };
      }
      if (url.includes("/api/jobs/job-1") && options?.method === "DELETE") {
        deleteCalls.push(url);
        return { body: { message: "Job data permanently deleted." } };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Tracker" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete Example Co / Automation Engineer" }));

    expect(confirmSpy).toHaveBeenCalledWith("Permanently delete local data for Example Co / Automation Engineer?");
    expect(deleteCalls).toEqual(["http://127.0.0.1:8001/api/jobs/job-1"]);
    expect(await screen.findByText("Job data permanently deleted.")).toBeInTheDocument();
    expect(screen.queryByText("Example Co")).not.toBeInTheDocument();
  });

  it("navigates Karen action shortcuts to the matching workflow section", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: blockedWorkspace() };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);
    await userEvent.click((await screen.findAllByRole("button", { name: "Review requirements" }))[0]);

    expect(await screen.findByRole("heading", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByText("Application Requirements")).toBeInTheDocument();
  });

  it("loads persistent Karen chat, sends chat payloads, and reloads state", async () => {
    const chatBodies: unknown[] = [];
    let agentLoads = 0;
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent/chat")) {
        chatBodies.push(JSON.parse(String(init?.body)));
        return { body: { context: { selected_job_id: "job-1", session_id: "session-1" } } };
      }
      if (url.includes("/api/agent")) {
        agentLoads += 1;
        return { body: agentState(agentLoads) };
      }
      return { body: {} };
    });

    render(<App />);

    expect(await screen.findByRole("complementary", { name: "Karen chat" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask Karen")).toBeInTheDocument();
    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
    expect(screen.getByLabelText("Karen workflow summary")).toHaveTextContent("Requirements Review");
    await userEvent.type(screen.getByPlaceholderText("Ask Karen"), "What next?");
    await userEvent.click(screen.getByRole("button", { name: "Ask Karen" }));

    await waitFor(() => expect(agentLoads).toBeGreaterThanOrEqual(2));
    expect(screen.getByPlaceholderText("Ask Karen")).toHaveValue("");
    expect(chatBodies).toEqual([
      {
        message: "What next?",
        selected_job_id: "job-1",
        session_id: "session-1",
      },
    ]);
  });

  it("sends Karen quick prompts without changing typed composer text", async () => {
    const chatBodies: unknown[] = [];
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent/chat")) {
        chatBodies.push(JSON.parse(String(init?.body)));
        return { body: { context: { selected_job_id: "job-1", session_id: "session-1" } } };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);

    const composer = await screen.findByPlaceholderText("Ask Karen");
    await userEvent.type(composer, "Draft question");
    await userEvent.click(screen.getByRole("button", { name: "What should I do next?" }));

    await waitFor(() => expect(chatBodies).toHaveLength(1));
    expect(chatBodies[0]).toMatchObject({ message: "What should I do next?" });
    expect(composer).toHaveValue("Draft question");
  });

  it("prevents duplicate Karen sends while one request is active", async () => {
    const chatBodies: unknown[] = [];
    let resolveChat: (value: MockResponse) => void = () => undefined;
    const pendingChat = new Promise<MockResponse>((resolve) => {
      resolveChat = resolve;
    });
    mockFetch(async (url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent/chat")) {
        chatBodies.push(JSON.parse(String(init?.body)));
        return pendingChat;
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);

    const composer = await screen.findByPlaceholderText("Ask Karen");
    await userEvent.type(composer, "Only once");
    const form = composer.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    fireEvent.submit(form!);

    await waitFor(() => expect(chatBodies).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Asking Karen..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Asking Karen..." })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByLabelText("Job")).toBeDisabled();
    expect(screen.getByRole("button", { name: "What should I do next?" })).toBeDisabled();
    expect(composer).toBeDisabled();
    resolveChat({ body: { context: { selected_job_id: "job-1", session_id: "session-1" } } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask Karen" })).toBeInTheDocument());
  });

  it("renders Karen messages with speakers, timestamps, actions, and preserved line breaks", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent")) {
        return {
          body: agentState(1, [
            {
              role: "user",
              content: "Status?",
              timestamp: "2026-06-02T10:15:00.000Z"
            },
            {
              role: "assistant",
              content: "Line one\nLine two",
              timestamp: "2026-06-02T10:16:00.000Z",
              actions: ["review_requirements"]
            }
          ])
        };
      }
      return { body: {} };
    });

    render(<App />);

    expect(await screen.findByText("You")).toBeInTheDocument();
    expect(screen.getByText("Karen")).toBeInTheDocument();
    expect(screen.getByText("Status?")).toBeInTheDocument();
    expect(screen.getByText((_, node) => node?.textContent === "Line one\nLine two")).toBeInTheDocument();
    expect(screen.getByLabelText("Message actions")).toHaveTextContent("Review requirements");
  });

  it("scrolls the Karen transcript to new messages", async () => {
    const scrollTo = vi.fn();
    const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo
    });
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent")) {
        return {
          body: agentState(1, [
            {
              role: "assistant",
              content: "Latest reply",
              timestamp: "2026-06-02T10:20:00.000Z"
            }
          ])
        };
      }
      return { body: {} };
    });

    render(<App />);

    await screen.findByText("Latest reply");
    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    expect(scrollTo).toHaveBeenCalledWith({ top: expect.any(Number), behavior: "smooth" });
    if (originalScrollTo) {
      Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    } else {
      delete HTMLElement.prototype.scrollTo;
    }
  });

  it("submits Karen composer with Enter and keeps Shift+Enter as a newline", async () => {
    const chatBodies: unknown[] = [];
    mockFetch((url, init) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent/chat")) {
        chatBodies.push(JSON.parse(String(init?.body)));
        return { body: { context: { selected_job_id: "job-1", session_id: "session-1" } } };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      return { body: {} };
    });

    render(<App />);

    const composer = await screen.findByPlaceholderText("Ask Karen");
    await userEvent.type(composer, "Line one{Shift>}{Enter}{/Shift}Line two");
    expect(composer).toHaveValue("Line one\nLine two");
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() => expect(chatBodies).toHaveLength(1));
    expect(chatBodies[0]).toMatchObject({ message: "Line one\nLine two" });
  });

  it("keeps one Karen chat panel available while switching pages", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
      }
      if (url.includes("/api/agent")) {
        return { body: agentState(1) };
      }
      if (url.includes("/api/jobs/job-1/workspace")) {
        return { body: blockedWorkspace() };
      }
      if (url.endsWith("/api/tracker")) {
        return {
          body: {
            records: [jobRecord()],
            status_options: trackerStatusOptions(),
            status_filters: trackerStatusFilters()
          }
        };
      }
      return { body: {} };
    });

    render(<App />);

    expect(await screen.findByRole("complementary", { name: "Karen chat" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Jobs" }));
    expect(screen.getByRole("complementary", { name: "Karen chat" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tracker" }));
    expect(screen.getByRole("complementary", { name: "Karen chat" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Agent Karen" }));

    expect(screen.getAllByPlaceholderText("Ask Karen")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Ask Karen" })).toHaveLength(1);
    expect(screen.getByRole("log", { name: "Karen transcript" })).toBeInTheDocument();
    const resizeHandle = screen.getByRole("separator", { name: "Resize Karen panel" });
    expect(resizeHandle).toHaveAttribute("aria-valuenow", "380");
    fireEvent.keyDown(resizeHandle, { key: "ArrowLeft" });
    expect(resizeHandle).toHaveAttribute("aria-valuenow", "400");
    expect(localStorage.getItem("karenPanelWidth")).toBe("400");
    expect(screen.getByRole("heading", { name: "Karen Dashboard" })).toBeInTheDocument();
    expect(screen.getAllByText("Review requirements").length).toBeGreaterThan(0);
  });
});

function mockFetch(handler: (url: string, init?: RequestInit) => MockResponse | Promise<MockResponse>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const result = await handler(url, init);
      const status = result.status ?? 200;
      const contentType = result.contentType ?? "application/json";
      const body = result.body ?? {};
      return new Response(
        contentType.includes("json") ? JSON.stringify(body) : String(body),
        {
          status,
          headers: { "content-type": contentType },
        }
      );
    })
  );
}

function candidateProfile() {
  return {
    candidate_profile: {
      profile_status: "draft",
      source_documents: {
        cv: { file_path: "/tmp/cv.pdf", parsed: true },
        optional_documents: []
      },
      cv_extracted: {
        identity: {
          first_name: "Taylor",
          last_name: "Example",
          gender: "Diverse",
          email: "taylor@example.com",
          phone: "+49123456789",
          location: "Berlin",
          street_address: "Main Street",
          street_number: "1",
          postal_code: "10115",
          city: "Berlin",
          country: "Germany",
          nationality: "German"
        },
        work_experience: ["Built automation workflows"],
        education: [],
        skills: ["Python"],
        languages: ["English"],
        certifications: [],
        projects: [],
        references: []
      },
      candidate_preferences: {
        target_roles: [],
        target_locations: [],
        remote_preference: [],
        employment_type: [],
        seniority_level: []
      }
    }
  };
}

function candidateProfileWithoutCv() {
  return {
    ...candidateProfile(),
    candidate_profile: {
      ...candidateProfile().candidate_profile,
      source_documents: {
        ...candidateProfile().candidate_profile.source_documents,
        cv: { file_path: "", parsed: false }
      },
      cv_extracted: {
        ...candidateProfile().candidate_profile.cv_extracted,
        identity: {
          ...candidateProfile().candidate_profile.cv_extracted.identity,
          first_name: "",
          last_name: "",
          gender: null,
          email: "",
          phone: "",
          street_address: "",
          street_number: "",
          postal_code: "",
          city: "",
          country: "",
          nationality: ""
        },
        work_experience: [],
        skills: [],
        languages: [],
        references: []
      }
    }
  };
}

function candidateProfileWithReferenceUploads() {
  return {
    ...candidateProfile(),
    candidate_profile: {
      ...candidateProfile().candidate_profile,
      source_documents: {
        ...candidateProfile().candidate_profile.source_documents,
        optional_documents: [
          {
            file_path: "/tmp/manager-reference.pdf",
            file_name: "manager-reference.pdf",
            document_type: "reference",
            parsed: true
          },
          {
            file_path: "/tmp/cert.pdf",
            file_name: "cert.pdf",
            document_type: "certificate",
            parsed: true
          }
        ]
      },
      cv_extracted: {
        ...candidateProfile().candidate_profile.cv_extracted,
        references: ["Former manager reference"]
      }
    }
  };
}

function candidateProfileWithoutReferences() {
  return {
    ...candidateProfile(),
    candidate_profile: {
      ...candidateProfile().candidate_profile,
      source_documents: {
        ...candidateProfile().candidate_profile.source_documents,
        optional_documents: [
          {
            file_path: "/tmp/cert.pdf",
            file_name: "cert.pdf",
            document_type: "certificate",
            parsed: true
          }
        ]
      },
      cv_extracted: {
        ...candidateProfile().candidate_profile.cv_extracted,
        references: []
      }
    }
  };
}

function jobExtraction() {
  return {
    source_url: "https://example.com/jobs/1",
    extracted_data: {
      title: "Automation Engineer",
      company: "Example Co",
      location: "Berlin",
      remote_policy: "Hybrid",
      apply_url: "https://example.com/apply/1",
      salary: "",
      posted_date: "",
      source_job_id: "external-1",
      description: "Build workflows.",
      requirements: ["Python"],
      responsibilities: ["Maintain workflows"],
      nice_to_have_skills: ["FastAPI"],
      dynamic_fields: [
        {
          name: "Department",
          value: "Platform",
          category: "team",
          source_text: "Platform",
          confidence: "medium"
        }
      ],
      missing_or_uncertain: []
    },
    apply_resolution: {
      status: "resolved",
      apply_url: "https://example.com/apply/1",
      confidence: "high",
      notes: "",
      evidence: [],
      rejected_candidates: []
    },
    final_apply_url: "https://example.com/apply/1",
    apply_url_messages: { errors: [], warnings: [], info: [] }
  };
}

function normalizedJob() {
  return {
    id: "job-1",
    title: "Automation Engineer",
    company: "Example Co",
    source_url: "https://example.com/jobs/1",
    apply_url: "https://example.com/apply/1",
    retrieval_mode: "url"
  };
}

function jobRecord() {
  return {
    job_id: "job-1",
    title: "Automation Engineer",
    company: "Example Co",
    source_url: "https://example.com/jobs/1",
    retrieval_mode: "url",
    status: "new"
  };
}

function jobRecord2() {
  return {
    job_id: "job-2",
    title: "Data Analyst",
    company: "Example Analytics",
    source_url: "https://example.com/jobs/2",
    apply_url: "https://example.com/apply/2",
    retrieval_mode: "url",
    status: "ready_to_apply",
    last_updated: "2026-06-02T09:00:00.000Z"
  };
}

function trackerStatusOptions() {
  return [
    { value: "new", label: "New", badge: "missing", user_editable: true },
    { value: "analyzed", label: "Analyzed", badge: "needs-review", user_editable: false },
    { value: "interesting", label: "Interesting", badge: "needs-review", user_editable: true },
    { value: "rejected_by_user", label: "Not interested", badge: "blocked", user_editable: true },
    { value: "application_draft", label: "Application Draft", badge: "needs-review", user_editable: false },
    { value: "ready_to_apply", label: "Ready to Apply", badge: "ready", user_editable: false },
    { value: "agent_assistance_attempted", label: "Agent Assistance Attempted", badge: "needs-review", user_editable: false },
    { value: "applied_manually", label: "Applied Manually", badge: "complete", user_editable: true },
    { value: "applied_with_agent_assistance", label: "Applied with Agent Assistance", badge: "complete", user_editable: true },
    { value: "interview", label: "Interview", badge: "complete", user_editable: true },
    { value: "rejected", label: "Rejected", badge: "blocked", user_editable: true },
    { value: "offer", label: "Offer", badge: "complete", user_editable: true },
    { value: "closed", label: "Closed", badge: "blocked", user_editable: true }
  ];
}

function trackerStatusFilters() {
  return [
    { label: "All", statuses: trackerStatusOptions().map((option) => option.value) },
    { label: "New", statuses: ["new"] },
    { label: "In progress", statuses: ["analyzed", "interesting"] },
    { label: "Application Draft", statuses: ["application_draft"] },
    { label: "Ready", statuses: ["ready_to_apply"] },
    { label: "Agent Attempted", statuses: ["agent_assistance_attempted"] },
    { label: "Applied", statuses: ["applied_manually", "applied_with_agent_assistance"] },
    { label: "Interview / Offer", statuses: ["interview", "offer"] },
    { label: "Closed", statuses: ["rejected", "closed"] },
    { label: "Not interested", statuses: ["rejected_by_user"] }
  ];
}

function blockedWorkspace() {
  return {
    job: normalizedJob(),
    requirements: null,
    package: null,
    package_summary: null,
    fill_plan: null,
    fill_plan_review: null,
    package_blockers: ["Discover application requirements."],
    fill_plan_generation_blockers: ["Discover application requirements."],
    apply_blockers: ["Discover application requirements for this apply URL."],
    active_browser_use_session: null,
    browser_use_runner_count: 0
  };
}

function readyWorkspace2() {
  return {
    ...readyWorkspace(),
    job: {
      id: "job-2",
      title: "Data Analyst",
      company: "Example Analytics",
      source_url: "https://example.com/jobs/2",
      apply_url: "https://example.com/apply/2",
      retrieval_mode: "url"
    },
    requirements: {
      ...readyWorkspace().requirements,
      job_id: "job-2"
    },
    package: {
      ...readyWorkspace().package,
      job_id: "job-2"
    },
    fill_plan: { job_id: "job-2", review_status: "reviewed" }
  };
}

function coverLetterWorkspace() {
  return {
    ...readyWorkspace(),
    package: {
      job_id: "job-1",
      status: "approved",
      artifacts: [
        {
          id: "cover",
          type: "cover_letter",
          label: "Cover Letter",
          content: "Dear hiring team,"
        }
      ]
    }
  };
}

function browserActiveWorkspace() {
  return {
    ...readyWorkspace(),
    active_browser_use_session: {
      pid: 1234,
      url: "https://example.com/apply/1"
    },
    browser_use_runner_count: 1
  };
}

function readyWorkspace() {
  return {
    job: normalizedJob(),
    requirements: {
      job_id: "job-1",
      review_status: "reviewed",
      job_preserving: true,
      required_documents: [{ label: "CV", required: true }],
      upload_expectations: [],
      screening_questions: [],
      custom_form_fields: [],
      profile_fields: [],
      consent_requirements: [],
      privacy_login_ats_gates: [],
      deadlines: [],
      contact_or_fallback: [],
      missing_or_uncertain: [],
      source_evidence: [],
      confidence: "high"
    },
    package: {
      job_id: "job-1",
      status: "approved",
      artifacts: [
        {
          id: "summary",
          type: "application_summary",
          label: "Application Summary",
          content: "Ready summary"
        }
      ]
    },
    package_summary: { selected_experience_units: [] },
    fill_plan: { job_id: "job-1", review_status: "reviewed" },
    fill_plan_review: { required_rows: [], optional_rows: [], upload_rows: [] },
    package_blockers: [],
    fill_plan_generation_blockers: [],
    apply_blockers: [],
    active_browser_use_session: null,
    browser_use_runner_count: 0
  };
}

function packageReadyWorkspace() {
  return {
    ...readyWorkspace(),
    package: null,
    package_summary: null,
    fill_plan: null,
    fill_plan_review: null,
    package_blockers: [],
    fill_plan_generation_blockers: ["Generate and review application package."]
  };
}

function fillPlanReadyWorkspace() {
  return {
    ...readyWorkspace(),
    fill_plan: null,
    fill_plan_review: null,
    fill_plan_generation_blockers: []
  };
}

function fillPlanReviewWorkspace() {
  return {
    ...readyWorkspace(),
    fill_plan: { job_id: "job-1", review_status: "draft" },
    apply_blockers: ["Review the application fill plan before applying."]
  };
}

function agentState(loadCount: number, messages: ApiRecord[] = []) {
  return {
    context: { selected_job_id: "job-1", session_id: "session-1" },
    state: {
      session_id: "session-1",
      selected_job_id: "job-1",
      blockers: [],
      errors: [],
      next_allowed_actions: ["review_requirements"],
      pending_gate: "requirements_review",
      artifacts_present: { requirements: loadCount > 1 }
    },
    messages,
    action_labels: { review_requirements: "Review requirements" }
  };
}

function agentFillPlanState(reviewed: boolean) {
  return {
    context: { selected_job_id: "job-1", session_id: "session-1" },
    state: reviewed
      ? {
          session_id: "session-1",
          selected_job_id: "job-1",
          blockers: [],
          errors: [],
          next_allowed_actions: ["prepare_apply_assistance"],
          pending_gate: null,
          artifacts_present: { fill_plan: true }
        }
      : {
          session_id: "session-1",
          selected_job_id: "job-1",
          blockers: ["Review the application fill plan before applying."],
          errors: [],
          next_allowed_actions: ["review_fill_plan"],
          pending_gate: "fill_plan_review",
          artifacts_present: { fill_plan: true }
        },
    messages: [],
    action_labels: {
      review_fill_plan: "Approve fill plan",
      prepare_apply_assistance: "Prepare apply assistance"
    }
  };
}
