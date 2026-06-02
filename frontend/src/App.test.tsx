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

  it("shows Jobs blockers and enables Apply only when review gates are complete", async () => {
    const workspaces = [blockedWorkspace(), readyWorkspace()];
    mockFetch((url) => {
      if (url.endsWith("/api/candidate-profile")) {
        return { body: { profile: candidateProfile(), options: {} } };
      }
      if (url.endsWith("/api/jobs")) {
        return { body: { records: [jobRecord()] } };
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
    expect(screen.getByRole("button", { name: "Ask Karen" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask Karen" })).toHaveAttribute("aria-busy", "true");
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
        return { body: { records: [jobRecord()] } };
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
