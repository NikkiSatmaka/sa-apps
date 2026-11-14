import { http, HttpResponse } from "msw";
import { successEnvelope } from "../../fixtures/envelope";
import {
  makeAdminUsers,
  makeAvailableSA,
  makeMonthlyUtilization,
  makePendingProject,
  makeProjectUtilization,
  makeStatusSummary,
  makeUtilizationSummary,
} from "../../fixtures/shell";
import { api } from "../base";

/** Handler default grup shell + dashboard (tiket #69). `GET /projects` ada di grup proyek. */
export const shellHandlers = [
  // "Tugas saya" di dashboard SA (#126): default kosong; test spesifik menimpa dengan `server.use`.
  http.get(api("/subtasks/saya"), () => HttpResponse.json(successEnvelope({ items: [], total: 0 }))),
  http.get(api("/projects/status-summary"), () => HttpResponse.json(successEnvelope(makeStatusSummary()))),
  http.get(api("/projects/pending-assignment"), () => HttpResponse.json(successEnvelope([makePendingProject()]))),
  http.post(api("/projects/:id/provision-folder"), () =>
    HttpResponse.json(
      successEnvelope({ id_project: "x", folder_provisioning_status: "pending", folder_provisioning_triggered: true }),
    ),
  ),
  http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([makeAvailableSA()]))),
  http.get(api("/sa/utilization"), () => HttpResponse.json(successEnvelope(makeMonthlyUtilization()))),
  http.get(api("/utilization/summary"), () => HttpResponse.json(successEnvelope(makeUtilizationSummary()))),
  http.get(api("/utilization/projects"), () => HttpResponse.json(successEnvelope(makeProjectUtilization()))),
  http.get(api("/admin/users"), () => HttpResponse.json(successEnvelope(makeAdminUsers()))),
  http.patch(api("/admin/users/:id/role"), () => HttpResponse.json(successEnvelope(null))),
];
