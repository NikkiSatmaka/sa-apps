import { expect, test, type Page, type Route } from "@playwright/test";

const projectId = "PRJ-E2E-EMAIL-203";
const operationId = "email-operation-203";
const operation = {
  id: operationId,
  operation_type: "email_delivery",
  action: "send_assignment_email",
  status: "failed",
  attempts: [{
    attempt: 1,
    status: "failed",
    started_at: "2026-11-17T10:00:00Z",
    finished_at: "2026-11-17T10:00:01Z",
    outcome: "Gmail did not confirm message delivery.",
    actionable_error: "Check the recipient status before manually sending.",
  }],
  started_at: "2026-11-17T10:00:00Z",
  finished_at: "2026-11-17T10:00:01Z",
  outcome: "Gmail did not confirm message delivery.",
  actionable_error: "Check the recipient status before manually sending.",
  retryable: false,
  project_id: projectId,
  context: { event_type: "assignment", reference_id: projectId },
};
const project = {
  id_project: projectId,
  project_name: "Email recovery fixture",
  customer_name: "Example customer",
  status: "Assigned",
  qualification_state: "Qualified",
  previous_status: null,
  lost_reason: null,
  dq_number: null,
  bant_score: null,
  bant_detail: null,
  qualification: null,
  use_case_tags: [],
  target_submit: null,
  created_by: null,
  product_pic: null,
  sales_pic: null,
  lead_sa: null,
  assigned_sa: null,
  collaborators: [],
  source_documents: [],
  gdrive_folder_id: null,
  folder_provisioning_status: null,
  folder_provisioning_operation: null,
  integration_operations: [operation],
  created_at: "2026-11-17T09:00:00Z",
  updated_at: "2026-11-17T09:00:00Z",
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", json: body });
}

async function jsonWithRefreshCookie(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "set-cookie": "refresh_token=fixture-refresh; Path=/api/v1/auth; HttpOnly; SameSite=Lax" },
    json: body,
  });
}


async function installFixtures(page: Page, operationFixture = operation) {
  let currentRole = "SA";
  let repaired = false;
  const repairRequests: { path: string; method: string; body: unknown }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (path === "/auth/config") return json(route, { demo_mode: true });
    if (path === "/auth/demo-login" && method === "POST") {
      const body = request.postDataJSON() as { role?: string };
      currentRole = body.role ?? "SA";
      return jsonWithRefreshCookie(route, {
        user: {
          id: "00000000-0000-4000-8000-000000000001",
          email: "demo-lead@portal-sa.local",
          name: "Demo Lead SA",
          role: currentRole,
          is_admin: currentRole === "Lead_SA",
        },
        tokens: { access_token: "fixture-app-session", expires_in: 900 },
      });
    }
    if (path === "/auth/refresh" && method === "POST") {
      const cookie = request.headers()["cookie"] ?? "";
      if (!cookie.includes("refresh_token=fixture-refresh")) {
        return json(route, { detail: "Refresh cookie tidak ditemukan." }, 401);
      }
      return json(route, { access_token: "fixture-app-session", expires_in: 900 });
    }
    if (path === "/auth/me" && method === "GET") {
      if (!request.headers()["authorization"]) return json(route, { message: "Unauthorized" }, 401);
      return json(route, {
        id: "00000000-0000-4000-8000-000000000001",
        email: "demo-lead@portal-sa.local",
        name: "Demo Lead SA",
        role: currentRole,
        is_admin: currentRole === "Lead_SA",
      });
    }
    if (path === `/projects/${projectId}` && method === "GET") {
      const detail = repaired
        ? { ...operationFixture, context: { ...operationFixture.context, manual_repair: {
          actor_user_id: "00000000-0000-4000-8000-000000000001",
          repaired_at: "2026-11-17T10:05:00Z",
          recipient_checked_not_received: true,
          manually_delivered_outside_app: true,
        } } }
        : operationFixture;
      return json(route, { data: { ...project, integration_operations: [detail] } });
    }
    if (path === `/projects/${projectId}/story`) {
      return json(route, { data: { items: [], total: 0, page: 1, page_size: 5, total_pages: 1 } });
    }
    if (path === `/projects/${projectId}/integration-operations/${operationId}/repair` && method === "POST") {
      repairRequests.push({ path, method, body: request.postDataJSON() });
      repaired = true;
      return json(route, {
        data: {
          ...operationFixture,
          context: { ...operationFixture.context, manual_repair: {
            actor_user_id: "00000000-0000-4000-8000-000000000001",
            repaired_at: "2026-11-17T10:05:00Z",
            recipient_checked_not_received: true,
            manually_delivered_outside_app: true,
          } },
        },
        message: "Operator-confirmed manual email recovery recorded; provider delivery was not confirmed.",
      });
    }
    if (path === `/projects/${projectId}/tim-sa`) return json(route, { data: { sa_utama: null, sa_tambahan: [] } });
    if (path === `/projects/${projectId}/comments` || path === `/projects/${projectId}/collaborators`) {
      return json(route, { data: { items: [], total: 0 } });
    }
    return json(route, { data: [] });
  });
  return repairRequests;
}

test("Lead SA records only an operator-confirmed manual email recovery", async ({ page }) => {
  const repairRequests = await installFixtures(page);
  await page.goto("/demo");
  await page.getByRole("button", { name: "Login sebagai Lead SA", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(`/projects/${projectId}`);

  const operationCard = page.locator("li").filter({ hasText: operation.action });
  await expect(page.getByRole("heading", { name: "Riwayat operasi integrasi" })).toBeVisible();
  await expect(operationCard).toContainText("Gmail did not confirm message delivery.");
  await expect(operationCard).toContainText("Check the recipient status before manually sending.");
  await expect(operationCard).toContainText("Status: failed · perlu ditangani");
  await expect(operationCard).toContainText("Percobaan 1: failed");
  await expect(operationCard).toContainText("Dimulai:");
  await expect(operationCard).toContainText("Selesai:");
  await operationCard.getByRole("button", { name: "Rekonsiliasi manual" }).click();

  const dialog = page.getByRole("dialog", { name: "Konfirmasi pemulihan email manual" });
  await expect(dialog).toContainText("Portal SA tidak akan mengirim ulang email");
  const confirmButton = dialog.getByRole("button", { name: "Catat pemulihan manual" });
  await expect(confirmButton).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /memastikan penerima belum menerima/ }).check();
  await expect(confirmButton).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /mengirim notifikasi secara manual di luar aplikasi/ }).check();
  await confirmButton.click();

  await expect(operationCard).toContainText("Pemulihan manual dikonfirmasi operator");
  await expect(operationCard).toContainText("provider delivery was not confirmed");
  await expect(operationCard.getByRole("button", { name: "Rekonsiliasi manual" })).toHaveCount(0);
  expect(repairRequests).toEqual([{
    path: `/projects/${projectId}/integration-operations/${operationId}/repair`,
    method: "POST",
    body: { recipient_checked_not_received: true, manually_delivered_outside_app: true },
  }]);
});
test("explains a Drive permission failure and hides provider details until requested", async ({ page }) => {
  const providerError =
    '[set_permission_sa_team] Gagal setelah 3 percobaan. Error terakhir: <HttpError 403 when requesting permissions returned "The user does not have sufficient permissions for this file.". Details: "[{\'reason\': \'insufficientFilePermissions\'}]">';
  const driveOperation = {
    ...operation,
    operation_type: "drive_provisioning",
    action: "Provisioning folder Google Drive",
    outcome: "Drive provisioning failed",
    actionable_error: providerError,
    attempts: operation.attempts.map((attempt) => ({
      ...attempt,
      outcome: "Drive provisioning failed",
      actionable_error: providerError,
    })),
  };
  await installFixtures(page, driveOperation);
  await page.goto("/demo");
  await page.getByRole("button", { name: "Login sebagai Lead SA", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(`/projects/${projectId}`);

  const operationCard = page.locator("li").filter({ hasText: driveOperation.action });
  await expect(operationCard).toContainText(
    "Akun layanan Google Drive tidak memiliki izin yang cukup untuk mengubah izin folder.",
  );
  await expect(operationCard).toContainText(/Minta admin Shared Drive memeriksa/);
  await expect(operationCard.getByText(/HttpError 403/)).toBeHidden();
  await operationCard.getByText("Detail teknis").click();
  await expect(operationCard.getByText(/HttpError 403/)).toBeVisible();
});
