import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const project = {
  id_project: "PRJ-E2E-001",
  project_name: "Demo Cloud Migration",
  customer_name: "Example Customer",
  status: "In Progress",
  qualification_state: "Qualified",
  dq_number: "DQ-E2E-01",
  bant_score: 80,
  use_case_tags: [],
  target_submit: "2026-12-01",
  updated_at: "2026-11-16T09:00:00Z",
};

const calendarStart = new Date();
calendarStart.setHours(10, 0, 0, 0);
const calendarEnd = new Date(calendarStart.getTime() + 60 * 60 * 1000);
const calendarEvent = {
  gcal_event_id: "demo-calendar-event",
  title: "Design review",
  description: "Review the project design",
  start: calendarStart.toISOString(),
  end: calendarEnd.toISOString(),
  is_all_day: false,
};

function projectDetails(provisioningStatus: "failed" | "pending") {
  const attempts: {
    attempt: number;
    status: string;
    started_at: string;
    finished_at: string | null;
    outcome: string | null;
    actionable_error: string | null;
  }[] = [
    {
      attempt: 1,
      status: "failed",
      started_at: "2026-11-16T08:00:00Z",
      finished_at: "2026-11-16T08:01:00Z",
      outcome: "permission_denied",
      actionable_error: "Check the Drive service account permissions.",
    },
  ];
  if (provisioningStatus === "pending") {
    attempts.push({
      attempt: 2,
      status: "pending",
      started_at: "2026-11-16T09:00:00Z",
      finished_at: null,
      outcome: null,
      actionable_error: null,
    });
  }

  return {
    ...project,
    created_by: null,
    product_pic: null,
    sales_pic: null,
    lead_sa: null,
    assigned_sa: null,
    collaborators: [],
    source_documents: [],
    gdrive_folder_id: null,
    folder_provisioning_status: provisioningStatus,
    folder_provisioning_operation: {
      status: provisioningStatus,
      attempts,
      started_at: "2026-11-16T08:00:00Z",
      finished_at: provisioningStatus === "failed" ? "2026-11-16T08:01:00Z" : null,
      outcome: provisioningStatus === "failed" ? "permission_denied" : null,
      actionable_error: provisioningStatus === "failed"
        ? "Check the Drive service account permissions."
        : null,
    },
    created_at: "2026-11-16T07:00:00Z",
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", json: body });
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value));
}

async function installFixtures(page: Page) {
  const requests: { path: string; method: string; body?: unknown }[] = [];
  let reprovisionStarted = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    const postData = request.postData();
    const body = postData ? asRecord(request.postDataJSON()) : {};
    requests.push({ path, method, body });

    if (path === "/auth/config") return json(route, { demo_mode: true });
    if (path === "/auth/demo-login") {
      const role = typeof body.role === "string" ? body.role : "SA";
      return json(route, {
        user: {
          id: "00000000-0000-4000-8000-000000000001",
          email: `demo-${role.toLowerCase()}@portal-sa.local`,
          name: `Demo ${role}`,
          role,
          is_admin: role === "Lead_SA",
        },
        tokens: { access_token: "fixture-app-session", expires_in: 900 },
      });
    }
    if (path === "/projects" && method === "GET") return json(route, [project]);
    if (path === `/projects/${project.id_project}` && method === "GET") {
      return json(route, projectDetails(reprovisionStarted ? "pending" : "failed"));
    }
    if (path === `/projects/${project.id_project}/provision-folder` && method === "POST") {
      reprovisionStarted = true;
      return json(route, {
        id_project: project.id_project,
        folder_provisioning_status: "pending",
        folder_provisioning_triggered: true,
      });
    }
    if (path === "/activity-logs" && method === "POST") {
      return json(route, { id_log: "LOG-E2E-001", ...body });
    }
    if (path === "/auth/calendar/exchange" && method === "POST") {
      return json(route, { connected: true });
    }
    if (path === "/calendar/sync" && method === "POST") {
      return json(route, { events: [calendarEvent] });
    }
    if (path === "/calendar/auth-url") {
      return json(route, { auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=fixture" });
    }
    return json(route, {});
  });
  return requests;
}

async function loginAsRole(page: Page, role: "SA" | "Sales" | "Lead_SA") {
  const buttonName = {
    SA: "Login sebagai SA",
    Sales: "Login sebagai Sales",
    Lead_SA: "Login sebagai Lead SA",
  }[role];
  await page.goto("/demo");
  await page.getByRole("button", { name: buttonName }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function loginAsSA(page: Page) {
  await loginAsRole(page, "SA");
}

test("Lead SA sees Drive failure details, retries, and sees pending attempt status", async ({ page }) => {
  const requests = await installFixtures(page);
  await loginAsRole(page, "Lead_SA");
  await page.goto(`/projects/${project.id_project}`);

  const driveSection = page.getByRole("region", { name: "Provisioning folder Google Drive" });
  await expect(driveSection.getByRole("alert")).toHaveText("Provisioning folder gagal");
  await expect(driveSection).toContainText("Hasil terakhir: permission_denied");
  await expect(driveSection).toContainText("Check the Drive service account permissions.");
  const history = driveSection.getByRole("list", { name: "Riwayat percobaan provisioning" });
  await expect(history).toContainText("Percobaan 1: failed");
  await driveSection.getByRole("button", { name: "Coba provisioning lagi" }).focus();
  await page.keyboard.press("Enter");

  await expect(driveSection.getByRole("status")).toHaveText("Provisioning folder sedang diproses");
  await expect(history).toContainText("Percobaan 2: pending");
  expect(requests).toContainEqual(expect.objectContaining({
    path: `/projects/${project.id_project}/provision-folder`,
    method: "POST",
  }));

  const violations = await new AxeBuilder({ page })
    .include("section[aria-labelledby='folder-provisioning-heading']")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(violations.violations).toEqual([]);
});

test("Sales can read the Drive failure but cannot retry provisioning", async ({ page }) => {
  await installFixtures(page);
  await loginAsRole(page, "Sales");
  await page.goto(`/projects/${project.id_project}`);

  const driveSection = page.getByRole("region", { name: "Provisioning folder Google Drive" });
  await expect(driveSection.getByRole("alert")).toHaveText("Provisioning folder gagal");
  await expect(driveSection.getByRole("list", { name: "Riwayat percobaan provisioning" }))
    .toContainText("Percobaan 1: failed");
  await expect(driveSection.getByRole("button", { name: "Coba provisioning lagi" })).toHaveCount(0);
});


const supportedViewports = [320, 768, 1024, 1440];

for (const width of supportedViewports) {
  test(`SA activity workflow is usable at ${width}px and meets automated WCAG 2.1 AA checks`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await installFixtures(page);
    await loginAsSA(page);

    await page.goto("/activity-logs");
    await expect(page.getByRole("heading", { name: "Activity Log", level: 1 })).toBeVisible();
    const form = page.getByRole("form", { name: "Form activity log" });
    await expect(form).toBeVisible();
    await expect(page.getByRole("link", { name: "Calendar Sync" })).toBeVisible();

    // Use native keyboard interaction for the required project-work path.
    const projectSelect = page.getByLabel("Proyek");
    await projectSelect.focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(projectSelect).toHaveValue(project.id_project);
    await page.getByLabel("Subtask").selectOption("Assessment");
    await page.getByLabel("Catatan").fill("Validated browser workflow for project work.");
    await page.getByRole("button", { name: "Simpan Activity Log" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alert")).toContainText("Activity log berhasil disimpan");
    expect(requests).toContainEqual(expect.objectContaining({
      path: "/activity-logs",
      method: "POST",
      body: expect.objectContaining({
        id_project: project.id_project,
        subtask_category: "Assessment",
        raw_notes: "Validated browser workflow for project work.",
      }),
    }));

    const violations = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(violations.violations).toEqual([]);
  });
}

test("Calendar handoff exchanges a one-time code without storing a Calendar token in browser storage", async ({ page }) => {
  const requests = await installFixtures(page);
  await loginAsSA(page);
  await page.goto("/activity-logs/calendar?code=one-time-calendar-handoff");

  await expect(page.getByRole("heading", { name: "Calendar Sync", level: 1 })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Google Calendar terhubung");
  await expect(page).toHaveURL(/\/activity-logs\/calendar$/);
  expect(requests).toContainEqual(expect.objectContaining({
    path: "/auth/calendar/exchange",
    method: "POST",
    body: { code: "one-time-calendar-handoff" },
  }));

  await page.getByRole("button", { name: /sync calendar/i }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Calendar tersinkronisasi");
  await expect(page.getByRole("heading", { name: "Design review" })).toBeVisible();
  expect(requests).toContainEqual(expect.objectContaining({
    path: "/calendar/sync",
    method: "POST",
    body: {},
  }));

  const storageKeys = await page.evaluate(() => Object.keys(window.localStorage));
  const calendarKeys = storageKeys.filter((key) => /calendar|google|gcal/i.test(key));
  expect(calendarKeys).toEqual([]);
  expect(storageKeys).not.toContain("access_token");
  expect(storageKeys).not.toContain("refresh_token");

  const violations = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(violations.violations).toEqual([]);
});
