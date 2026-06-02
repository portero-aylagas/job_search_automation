import { expect, test, type Page, type Route } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("top-level navigation renders without a backend server", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Candidate Profile" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Karen chat" })).toBeVisible();
  await expect(page.getByPlaceholder("Ask Karen")).toBeVisible();
  await expect(page.getByRole("separator", { name: "Resize Karen panel" })).toBeVisible();
  for (const name of ["Job Intake", "Jobs", "Tracker", "Agent Karen"]) {
    await page.getByRole("button", { name }).click();
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Karen chat" })).toBeVisible();
    await expect(page.getByRole("separator", { name: "Resize Karen panel" })).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Karen Dashboard" })).toBeVisible();
  await expect(page.getByPlaceholder("Ask Karen")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Ask Karen" })).toHaveCount(1);
});

test("Job Intake happy path extracts, reviews, and saves a job", async ({ page }) => {
  const saveBodies: unknown[] = [];
  await page.route("http://127.0.0.1:8001/api/job-intake/save", async (route) => {
    saveBodies.push(route.request().postDataJSON());
    await route.fulfill({ json: { message: "Added job.", job: normalizedJob() } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Job Intake" }).click();
  await page.getByLabel("Job URL").fill("https://example.com/jobs/1");
  await page.getByRole("button", { name: "Extract application data with AI" }).click();

  await expect(page.getByLabel("Title")).toHaveValue("Automation Engineer");
  await expect(page.getByLabel("Department")).toHaveValue("Platform");
  await page.getByLabel("Department").fill("Reliability");
  await page.getByRole("button", { name: "Add To Application Workflow" }).click();

  await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  expect(saveBodies).toHaveLength(1);
  expect((saveBodies[0] as any).dynamic_fields[0].value).toBe("Reliability");
});

test("Jobs workspace shows review gates and blocks Apply until ready", async ({ page }) => {
  let workspaceReady = false;
  await page.route("http://127.0.0.1:8001/api/jobs/job-1/workspace", async (route) => {
    await route.fulfill({ json: workspaceReady ? readyWorkspace() : blockedWorkspace() });
  });
  await page.route("http://127.0.0.1:8001/api/jobs/job-1/requirements/discover", async (route) => {
    workspaceReady = true;
    await delay(150);
    await route.fulfill({ json: { message: "Requirements saved." } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Jobs" }).click();

  await expect(page.getByRole("list", { name: "Selected job workflow steps" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Example Co / Automation Engineer" })).toBeVisible();
  await expect(page.getByText("Discover application requirements for this apply URL.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply to job with AI" })).toBeDisabled();

  await page.getByRole("button", { name: "Discover requirements from apply URL with AI" }).click();

  await expect(page.getByRole("button", { name: "Discovering requirements..." })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh requirements from apply URL with AI" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate application package with AI" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Apply to job with AI" })).toBeEnabled();
});

test("mobile viewport collapses Karen into a bottom drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const karenPanel = page.getByRole("complementary", { name: "Karen chat" });
  await expect(karenPanel).toHaveClass(/mobile-closed/);
  await expect(page.getByRole("button", { name: "Open Karen" })).toBeVisible();
  await page.getByRole("button", { name: "Open Karen" }).click();

  await expect(karenPanel).toHaveClass(/mobile-open/);
  await expect(page.getByRole("button", { name: "Close Karen" })).toBeVisible();
});

async function installApiMocks(page: Page) {
  await page.route("http://127.0.0.1:8001/api/**", async (route) => {
    const url = route.request().url();
    await route.fulfill({ json: responseFor(url, route) });
  });
}

function delay(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function responseFor(url: string, route: Route) {
  if (url.endsWith("/api/candidate-profile")) {
    return { profile: candidateProfile(), options: {} };
  }
  if (url.endsWith("/api/job-intake/extract")) {
    return jobExtraction();
  }
  if (url.endsWith("/api/job-intake/save")) {
    return { message: "Added job.", job: normalizedJob() };
  }
  if (url.endsWith("/api/jobs")) {
    return { records: [jobRecord()] };
  }
  if (url.endsWith("/api/tracker")) {
    return { records: [jobRecord()] };
  }
  if (url.includes("/api/jobs/job-1/workspace")) {
    return blockedWorkspace();
  }
  if (url.includes("/api/agent")) {
    return agentState();
  }
  if (route.request().method() === "POST") {
    return { message: "Saved." };
  }
  return {};
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
      dynamic_fields: [{ name: "Department", value: "Platform", confidence: "medium" }],
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
      artifacts: [{ id: "summary", type: "application_summary", label: "Application Summary", content: "Ready summary" }]
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

function agentState() {
  return {
    context: { selected_job_id: "job-1", session_id: "session-1" },
    state: {
      session_id: "session-1",
      selected_job_id: "job-1",
      blockers: [],
      errors: [],
      next_allowed_actions: ["review_requirements"],
      pending_gate: "requirements_review",
      artifacts_present: {}
    },
    messages: [],
    action_labels: { review_requirements: "Review requirements" }
  };
}
