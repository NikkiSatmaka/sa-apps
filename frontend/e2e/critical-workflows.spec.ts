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

const projectRecords = Array.from({ length: 101 }, (_, index) => {
  const number = String(index + 1).padStart(3, "0");
  const inProgress = index % 2 === 0;
  return {
    ...project,
    id_project: `PRJ-E2E-${number}`,
    project_name: index === 0
      ? project.project_name
      : `${inProgress ? "Beta" : "Alpha"} Project ${number}`,
    customer_name: `Example Customer ${number}`,
    status: inProgress ? "In Progress" : "Assigned",
  };
});

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
  const requests: { path: string; method: string; body?: unknown; search: string }[] = [];
  let reprovisionStarted = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    const postData = request.postData();
    const body = postData ? asRecord(request.postDataJSON()) : {};
    requests.push({ path, method, body, search: url.search });

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
    if (path === "/projects/status-summary" && method === "GET") {
      return json(route, []);
    }
    if (path === "/projects" && method === "GET") {
      const page = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "25");
      const statusFilter = url.searchParams.get("status");
      const searchTerm = url.searchParams.get("search")?.toLocaleLowerCase();
      const filtered = projectRecords.filter((item) =>
        (!statusFilter || item.status === statusFilter)
        && (!searchTerm || [
          item.project_name,
          item.customer_name,
          item.id_project,
        ].some((field) => field.toLocaleLowerCase().includes(searchTerm))),
      );
      return json(route, {
        data: {
          items: filtered.slice((page - 1) * pageSize, page * pageSize),
          total: filtered.length,
          page,
          page_size: pageSize,
          total_pages: Math.ceil(filtered.length / pageSize),
        },
        message: `Ditemukan ${filtered.length} proyek.`,
      });
    }
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
      return json(route, {
        events: [calendarEvent],
        integration_operation: {
          id: "calendar-sync-operation",
          operation_type: "calendar",
          action: "sync_calendar",
          status: "succeeded",
          attempts: [{
            attempt: 1,
            status: "succeeded",
            started_at: "2026-11-16T10:00:00Z",
            finished_at: "2026-11-16T10:00:01Z",
            outcome: "Loaded 1 events from Google Calendar.",
            actionable_error: null,
          }],
          started_at: "2026-11-16T10:00:00Z",
          finished_at: "2026-11-16T10:00:01Z",
          outcome: "Loaded 1 events from Google Calendar.",
          actionable_error: null,
          retryable: false,
          project_id: null,
          context: { action: "sync_calendar" },
        },
      });
    }
    if (path === "/calendar/auth-url") {
      return json(route, { auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=fixture" });
    }
    if (path === `/projects/${project.id_project}/story` && method === "GET") {
      return json(route, {
        data: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 },
        message: "Project story kosong.",
      });
    }
    if (path === "/projects/pending-assignment" && method === "GET") {
      return json(route, []);
    }
    if (path === "/sa/available" && method === "GET") {
      return json(route, []);
    }
    if (path === "/sa/utilization" && method === "GET") {
      return json(route, {
        data: {
          year: Number(url.searchParams.get("year") ?? new Date().getFullYear()),
          monthly_data: [],
          summary: { months: {}, total_hours: 0, sa_count: 0 },
        },
        message: "Utilisasi kosong.",
      });
    }
    if (path === "/utilization/summary" && method === "GET") {
      return json(route, {
        data: {
          year: Number(url.searchParams.get("year") ?? new Date().getFullYear()),
          work_type: {
            months: {},
            totals: { Project: 0, "Non-Project": 0 },
            grand_total: 0,
          },
          project_phase: { totals: {}, total: 0 },
        },
        message: "Ringkasan utilisasi kosong.",
      });
    }
    if (path === "/subtasks/saya" && method === "GET") {
      return json(route, {
        data: { items: [], total: 0, page: 1, page_size: 20, total_pages: 1 },
        message: "Tidak ada tugas.",
      });
    }
    if (path === "/utilization/projects" && method === "GET") {
      return json(route, []);
    }
    return json(route, {});
  });
  return requests;
}

async function loginAsRole(page: Page, role: "SA" | "Sales" | "Product" | "Lead_SA") {
  const buttonName = {
    SA: "Login sebagai SA",
    Sales: "Login sebagai Sales",
    Product: "Login sebagai Product Manager",
    Lead_SA: "Login sebagai Lead SA",
  }[role];
  await page.goto("/demo");
  await page.getByRole("button", { name: buttonName, exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function loginAsSA(page: Page) {
  await loginAsRole(page, "SA");
}
async function installRequesterWorkflowFixtures(page: Page, role: "Sales" | "Product") {
  const requests = await installFixtures(page);
  const projectId = `PRJ-${role.toUpperCase()}-INTAKE`;
  const productPic = { id: "00000000-0000-4000-8000-0000000000a1", name: "Product PIC", email: "product@example.test", role: "Product" };
  const salesPic = { id: "00000000-0000-4000-8000-0000000000b1", name: "Sales PIC", email: "sales@example.test", role: "Sales" };
  const workflowSchema = {
    schema_version: 1,
    groups: [{ key: "budget", title: "Budget" }],
    questions: [{
      name: "budget_status",
      group: "budget",
      type: "choice",
      label: "Status anggaran",
      short_label: "Status anggaran",
      required: true,
      choices: ["Sudah disetujui", "Dalam proses"],
      hint: null,
      placeholder: null,
      max_length: null,
      min_value: null,
      max_value: null,
      pattern: null,
      row: null,
      row_hint: null,
      display: null,
      show_char_count: false,
      header: false,
    }],
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (path === "/auth/config") {
      requests.push({ path, method, search: url.search });
      return json(route, { demo_mode: true });
    }
    if (path === "/auth/demo-login" && method === "POST") {
      const body = asRecord(request.postDataJSON());
      const loginRole = typeof body.role === "string" ? body.role : role;
      requests.push({ path, method, body, search: url.search });
      return json(route, {
        user: {
          id: "00000000-0000-4000-8000-000000000001",
          email: `demo-${loginRole.toLowerCase()}@portal-sa.local`,
          name: `Demo ${loginRole}`,
          role: loginRole,
          is_admin: loginRole === "Lead_SA",
        },
        tokens: { access_token: "fixture-app-session", expires_in: 900 },
      });
    }
    if (path === "/qualification/schema" && method === "GET") {
      requests.push({ path, method, search: url.search });
      return json(route, { data: workflowSchema, message: "Fixture qualification schema." });
    }
    if (path === "/projects/users/search" && method === "GET") {
      requests.push({ path, method, search: url.search });
      const people = url.searchParams.get("role") === "Product" ? [productPic] : [salesPic];
      return json(route, { data: people, message: "Fixture PICs." });
    }
    if (path === "/projects" && method === "POST") {
      const postData = request.postData() ?? "";
      requests.push({ path, method, body: postData, search: url.search });
      return json(route, {
        data: {
          id_project: projectId,
          project_name: `${role} intake fixture`,
          customer_name: "Example Customer",
          status: "Awaiting Assignment",
          bant_score: 65,
          sub_scores: null,
          feedback: null,
          scoring_triggered: false,
          files: [],
        },
        message: "Project fixture created.",
      }, 201);
    }
    return route.fallback();
  });
  return { requests, projectId, productPic, salesPic };
}

async function submitRequesterIntake(page: Page, role: "Sales" | "Product") {
  const fixtures = await installRequesterWorkflowFixtures(page, role);
  await loginAsRole(page, role);
  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { name: "Request SA" })).toBeVisible();
  await page.getByLabel(/Nama Proyek/).fill(`${role} intake fixture`);
  await page.getByLabel(/Nama Customer/).fill("Example Customer");
  await page.getByLabel(/Target Submit/).fill("2099-12-31");
  await page.getByLabel(/Estimasi Nilai Proyek/).fill("1500000");

  const productPIC = page.getByLabel(/Product Manager PIC/);
  if (role === "Sales") {
    await expect(productPIC.locator("option")).toHaveText(["Pilih Product Manager…", "Product PIC (product@example.test)"]);
    await productPIC.selectOption(fixtures.productPic.id);
    await expect(page.getByLabel(/Sales PIC/)).toHaveCount(0);
  } else {
    await expect(productPIC).toHaveCount(0);
    const salesPIC = page.getByLabel(/Sales PIC/);
    await expect(salesPIC.locator("option")).toHaveText(["Tanpa Sales", "Sales PIC (sales@example.test)"]);
    await salesPIC.selectOption(fixtures.salesPic.id);
  }
  await page.getByRole("button", { name: "Lanjut ke Kuesioner" }).click();
  await page.getByLabel(/Status anggaran/).selectOption("Sudah disetujui");
  await page.getByRole("button", { name: "Submit Request" }).click();
  await expect(page.getByRole("heading", { name: "Request SA terkirim" })).toBeVisible();
  return fixtures;
}

test("Sales requester project intake filters PICs and keeps Sales PIC implicit", async ({ page }) => {
  const { requests, productPic, projectId } = await submitRequesterIntake(page, "Sales");
  expect(requests.filter((request) => request.path === "/projects/users/search").map((request) =>
    new URLSearchParams(request.search).get("role"),
  )).toEqual(["Product"]);
  const create = requests.find((request) => request.path === "/projects" && request.method === "POST");
  expect(create?.body).toContain(`name="product_pic"\r\n\r\n${productPic.id}`);
  expect(create?.body).not.toContain('name="sales_pic"');
  expect(create?.body).toContain(`name="project_name"\r\n\r\nSales intake fixture`);
  expect(projectId).toBe("PRJ-SALES-INTAKE");
});

test("Product Manager requester project intake filters PICs and selects Sales PIC", async ({ page }) => {
  const { requests, salesPic, projectId } = await submitRequesterIntake(page, "Product");
  expect(requests.filter((request) => request.path === "/projects/users/search").map((request) =>
    new URLSearchParams(request.search).get("role"),
  )).toEqual(["Sales"]);
  const create = requests.find((request) => request.path === "/projects" && request.method === "POST");
  expect(create?.body).not.toContain('name="product_pic"');
  expect(create?.body).toContain(`name="sales_pic"\r\n\r\n${salesPic.id}`);
  expect(create?.body).toContain(`name="project_name"\r\n\r\nProduct intake fixture`);
  expect(projectId).toBe("PRJ-PRODUCT-INTAKE");
});
async function installAssignmentProgressionFixtures(page: Page) {
  const requests = await installFixtures(page);
  const projectId = "PRJ-LEAD-SA-WORKFLOW";
  const saId = "00000000-0000-4000-8000-000000000002";
  const leadId = "00000000-0000-4000-8000-000000000001";
  let status = "Awaiting Assignment";
  let assignedSA: string | null = null;
  const pendingProject = {
    id_project: projectId,
    project_name: "Lead SA assignment fixture",
    customer_name: "Example Customer",
    status: "Awaiting Assignment",
    bant_score: 80,
    use_case_tags: [],
    assigned_sa: null,
    assigned_at: null,
    target_submit: "2099-12-31",
    gdrive_folder_id: null,
    folder_provisioning_status: null,
  };
  const availablePeople = [
    { id: saId, name: "Fixture SA", email: "sa@example.test", role: "SA", active_project_count: 0 },
    { id: leadId, name: "Fixture Lead SA", email: "lead@example.test", role: "Lead_SA", active_project_count: 0 },
  ];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (path === "/projects/pending-assignment" && method === "GET") {
      requests.push({ path, method, search: url.search });
      return json(route, { data: status === "Awaiting Assignment" ? [pendingProject] : [] });
    }
    if (path === "/sa/available" && method === "GET") {
      requests.push({ path, method, search: url.search });
      return json(route, { data: availablePeople });
    }
    if (path === `/projects/${projectId}/assign` && method === "POST") {
      const body = asRecord(request.postDataJSON());
      requests.push({ path, method, body, search: url.search });
      assignedSA = typeof body.sa_id === "string" ? body.sa_id : null;
      status = "Assigned";
      return json(route, {
        data: {
          project: { ...pendingProject, status, assigned_sa: assignedSA },
          assigned_sa_name: "Fixture SA",
          notification_sent: true,
          folder_provisioning_triggered: false,
        },
        message: "Assignment fixture saved.",
      });
    }
    if (path === `/projects/${projectId}` && method === "GET") {
      requests.push({ path, method, search: url.search });
      return json(route, {
        data: {
          ...pendingProject,
          status,
          assigned_sa: assignedSA ? { id: assignedSA, name: "Fixture SA", email: "sa@example.test" } : null,
          product_pic: null,
          sales_pic: null,
          lead_sa: { id: leadId, name: "Fixture Lead SA", email: "lead@example.test" },
          created_by: null,
          qualification_state: "Qualified",
          collaborators: [],
          source_documents: [],
          integration_operations: [],
          updated_at: "2026-11-16T09:00:00Z",
          created_at: "2026-11-16T09:00:00Z",
        },
      });
    }
    if (path === `/projects/${projectId}/tim-sa` && method === "GET") {
      return json(route, { data: { sa_utama: assignedSA ? { id: assignedSA } : null, sa_tambahan: [] } });
    }
    if (path === `/projects/${projectId}/status` && method === "PATCH") {
      const body = asRecord(request.postDataJSON());
      requests.push({ path, method, body, search: url.search });
      status = typeof body.new_status === "string" ? body.new_status : status;
      return json(route, { data: { status }, message: `Status changed to ${status}.` });
    }
    return route.fallback();
  });
  return { requests, projectId, saId, leadId };
}

test("Lead SA assignment hands the project to its SA and SA progresses assigned work to Submitted", async ({ page }) => {
  const { requests, projectId, saId, leadId } = await installAssignmentProgressionFixtures(page);
  await loginAsRole(page, "Lead_SA");
  await page.goto("/dashboard/lead-sa");
  await expect(page.getByRole("heading", { name: "Dashboard Lead SA" })).toBeVisible();
  await page.getByRole("button", { name: "Assign SA", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Assign SA ke Proyek" })).toBeVisible();
  await page.getByRole("button", { name: /Fixture SA/ }).click();
  await page.getByRole("button", { name: "Konfirmasi", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Assign SA ke Proyek" })).toHaveCount(0);
  expect(requests).toContainEqual(expect.objectContaining({
    path: `/projects/${projectId}/assign`,
    method: "POST",
    body: { sa_id: saId, lead_sa_id: leadId },
  }));

  await loginAsRole(page, "SA");
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByRole("heading", { name: "Lead SA assignment fixture" })).toBeVisible();
  await page.getByRole("button", { name: "Tandai Submitted", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Tandai Submitted" })).toContainText("Assigned");
  await page.getByRole("button", { name: "Konfirmasi", exact: true }).click();
  await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
  expect(requests).toContainEqual(expect.objectContaining({
    path: `/projects/${projectId}/status`,
    method: "PATCH",
    body: { new_status: "Submitted" },
  }));
});



test("project pages retain filters and both activity pickers reach the final API page", async ({ page }) => {
  const requests = await installFixtures(page);
  await loginAsSA(page);
  await page.getByTitle("Proyek").click();

  const search = page.getByPlaceholder("Cari nama proyek atau customer...");
  await search.fill("beta");
  await page.getByRole("combobox").selectOption("In Progress");
  await expect(page.getByRole("button", { name: "Proyek Beta Project 003 - Example Customer 003" }))
    .toBeVisible();
  await expect(page.getByText("Menampilkan 20 dari 50 proyek")).toBeVisible();
  const previous = page.getByRole("button", { name: "Halaman sebelumnya" });
  const next = page.getByRole("button", { name: "Halaman berikutnya" });
  await expect(previous).toBeDisabled();
  await page.getByRole("button", { name: "Halaman berikutnya" }).click();
  await expect(page.getByRole("button", { name: "Proyek Beta Project 043 - Example Customer 043" }))
    .toBeVisible();
  await expect(search).toHaveValue("beta");
  await expect(page.getByRole("combobox")).toHaveValue("In Progress");
  await expect(previous).toBeEnabled();
  await expect(next).toBeEnabled();

  const pageTwo = requests
    .filter((request) => request.path === "/projects" && request.method === "GET")
    .map((request) => new URLSearchParams(request.search))
    .find((params) => params.get("page") === "2");
  expect(pageTwo?.get("status")).toBe("In Progress");
  expect(pageTwo?.get("search")).toBe("beta");
  expect(pageTwo?.get("sort")).toBe("-updated_at");
  expect(pageTwo?.get("page_size")).toBe("20");
  await next.click();
  await expect(page.getByRole("button", { name: "Proyek Beta Project 083 - Example Customer 083" }))
    .toBeVisible();
  await expect(page.getByRole("button", { name: "Proyek Beta Project 101 - Example Customer 101" }))
    .toBeVisible();
  await expect(page.getByText("Menampilkan 41–50 dari 50 proyek")).toBeVisible();
  await expect(next).toBeDisabled();

  await page.getByTitle("Activity Log").click();
  const activityProject = page.getByLabel("Proyek *", { exact: true });
  await expect(activityProject.locator('option[value="PRJ-E2E-101"]')).toHaveText("Beta Project 101");
  await activityProject.selectOption("PRJ-E2E-101");
  await expect(activityProject).toHaveValue("PRJ-E2E-101");

  await page.goto("/activity-logs/calendar#gcal_code=one-time-calendar-handoff");
  await expect(page.getByText("Google Calendar terhubung. Klik Sync Calendar untuk memuat event.", { exact: true }))
    .toBeVisible();
  await page.getByRole("button", { name: /sync calendar/i }).click();
  await expect(page.getByRole("heading", { name: "Design review" })).toBeVisible();
  await page.getByRole("button", { name: "Map ke Subtask" }).click();
  const calendarProject = page.getByLabel("Proyek *", { exact: true });
  await expect(calendarProject.locator('option[value="PRJ-E2E-101"]')).toHaveText("Beta Project 101");
  await calendarProject.selectOption("PRJ-E2E-101");
  await expect(calendarProject).toHaveValue("PRJ-E2E-101");
});

test("Lead SA sees Drive failure details, retries, and sees pending attempt status", async ({ page }) => {
  const requests = await installFixtures(page);
  await loginAsRole(page, "Lead_SA");
  await page.getByTitle("Proyek").click();
  await page.getByRole("button", {
    name: "Proyek Demo Cloud Migration - Example Customer 001",
    exact: true,
  }).click();

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
  await page.getByTitle("Proyek").click();
  await page.getByRole("button", {
    name: "Proyek Demo Cloud Migration - Example Customer 001",
    exact: true,
  }).click();

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

    await page.getByTitle("Activity Log").click();
    await expect(page.getByRole("heading", { name: "Activity Log", level: 1 })).toBeVisible();
    const form = page.getByRole("form", { name: "Form activity log" });
    await expect(form).toBeVisible();
    await expect(page.getByRole("link", { name: "Calendar Sync" })).toBeVisible();

    // Use native keyboard interaction for the required project-work path.
    const projectSelect = page.getByLabel("Proyek *", { exact: true });
    await projectSelect.focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(projectSelect).toHaveValue(project.id_project);
    await page.getByLabel("Subtask").selectOption("Assessment");
    await page.getByLabel("Catatan").fill("Validated browser workflow for project work.");
    await page.getByRole("button", { name: "Simpan Activity Log" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Activity log berhasil disimpan", { exact: true })).toBeVisible();
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
  await page.goto("/activity-logs/calendar#gcal_code=one-time-calendar-handoff");

  await expect(page.getByRole("heading", { name: "Calendar Sync", level: 1 })).toBeVisible();
  await expect(page.getByText("Google Calendar terhubung. Klik Sync Calendar untuk memuat event.", { exact: true }))
    .toBeVisible();
  await expect(page).toHaveURL(/\/activity-logs\/calendar$/);
  expect(requests).toContainEqual(expect.objectContaining({
    path: "/auth/calendar/exchange",
    method: "POST",
    body: { code: "one-time-calendar-handoff" },
  }));

  await page.getByRole("button", { name: /sync calendar/i }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Calendar tersinkronisasi/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Design review" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Status operasi Calendar" }))
    .toContainText("Status operasi: Berhasil");
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

test("Calendar mapping failure is visible and the form remains available for safe manual recovery", async ({ page }) => {
  await installFixtures(page);
  let mapAttempt = 0;
  await page.route("**/api/v1/calendar/map", async (route) => {
    mapAttempt += 1;
    if (mapAttempt > 1) {
      return json(route, {
        status: "success",
        data: {
          integration_operation: {
            id: "calendar-map-retry-operation",
            operation_type: "calendar",
            action: "map_event_to_project",
            status: "succeeded",
            attempts: [{
              attempt: 1,
              status: "succeeded",
              started_at: "2026-11-16T10:01:00Z",
              finished_at: "2026-11-16T10:01:01Z",
              outcome: "Calendar event mapped after manual recovery.",
              actionable_error: null,
            }],
            started_at: "2026-11-16T10:01:00Z",
            finished_at: "2026-11-16T10:01:01Z",
            outcome: "Calendar event mapped after manual recovery.",
            actionable_error: null,
            retryable: false,
            project_id: "PRJ-E2E-001",
            context: {
              gcal_event_id: calendarEvent.gcal_event_id,
              work_type: "Project",
              activity_log_id: "LOG-E2E-002",
            },
          },
        },
        message: "The event was mapped.",
      }, 201);
    }
    return json(route, {
      status: "error",
      data: {
        integration_operation: {
          id: "calendar-map-operation",
          operation_type: "calendar",
          action: "map_event_to_project",
          status: "failed",
          attempts: [{
            attempt: 1,
            status: "failed",
            started_at: "2026-11-16T10:00:00Z",
            finished_at: "2026-11-16T10:00:02Z",
            outcome: "The Calendar event was not mapped.",
            actionable_error: "Check the project activity log before trying again.",
          }],
          started_at: "2026-11-16T10:00:00Z",
          finished_at: "2026-11-16T10:00:02Z",
          outcome: "The Calendar event was not mapped.",
          actionable_error: "Check the project activity log before trying again.",
          retryable: false,
          project_id: "PRJ-E2E-001",
          context: {
            gcal_event_id: calendarEvent.gcal_event_id,
            work_type: "Project",
            activity_log_id: "LOG-E2E-001",
          },
        },
      },
      message: "The event was not mapped.",
    }, 409);
  });
  await loginAsSA(page);
  await page.goto("/activity-logs/calendar");
  await page.getByRole("button", { name: /sync calendar/i }).click();
  await page.getByRole("button", { name: "Map ke Subtask" }).click();
  await page.getByLabel("Proyek *", { exact: true }).selectOption(project.id_project);
  await page.getByLabel(/Subtask/).selectOption("Assessment");
  await page.getByRole("button", { name: "Simpan Mapping" }).click();

  const operation = page.getByRole("region", { name: "Status operasi Calendar" });
  await expect(operation).toContainText("Status operasi: Gagal");
  await expect(operation).toContainText("ID operasi: calendar-map-operation");
  await expect(operation).toContainText("Proyek: PRJ-E2E-001");
  await expect(operation).toContainText("Check the project activity log before trying again.");
  await expect(page.getByRole("heading", { name: "Map Event ke Subtask" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Simpan Mapping" })).toBeEnabled();
  await expect(page.getByText("✓ Sudah di-mapping")).toHaveCount(0);
  await page.getByRole("button", { name: "Simpan Mapping" }).click();
  await expect(operation).toContainText("Status operasi: Berhasil");
  await expect(operation).toContainText("Calendar event mapped after manual recovery.");
  await expect(page.getByText("✓ Sudah di-mapping")).toBeVisible();
});
