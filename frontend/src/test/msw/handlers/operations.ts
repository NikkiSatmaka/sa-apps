/**
 * Handler MSW grup operasi: assignment/reassign, kolaborator, handover-config,
 * activity log (+story/polish), dan Calendar Sync (backend + Google Calendar API).
 * Timpa per test dengan `server.use(...)` untuk skenario error/kosong.
 */
import { http, HttpResponse } from "msw";
import { successEnvelope } from "../../fixtures/envelope";
import {
  makeActivityLog,
  makeAvailableSA,
  makeCollaborator,
  makeStoryPage,
  makeUserSearchResult,
} from "../../fixtures/operations";
import { api } from "../base";

export const GCAL_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events";

export const operationsHandlers = [
  // Assignment
  http.get(api("/sa/available"), () =>
    HttpResponse.json(successEnvelope([makeAvailableSA(), makeAvailableSA({ id: "sa-2", name: "Eka Putri", email: "eka@example.com", active_project_count: 4 })]))
  ),
  http.post(api("/projects/:id/assign"), ({ params }) =>
    HttpResponse.json(successEnvelope({ id_project: params.id, assigned_sa: "sa-1", assigned_at: "2025-01-01T00:00:00Z", status: "Assigned" }))
  ),
  http.post(api("/projects/:id/reassign"), ({ params }) =>
    HttpResponse.json(successEnvelope({ id_project: params.id, assigned_sa: "sa-2", assigned_sa_name: "Eka Putri", status: "Assigned" }))
  ),

  // Kolaborator
  http.get(api("/projects/:id/collaborators"), () =>
    HttpResponse.json(successEnvelope({ items: [makeCollaborator()], total: 1 }))
  ),
  http.get(api("/projects/users/search"), () => HttpResponse.json(successEnvelope([makeUserSearchResult()]))),
  http.post(api("/projects/:id/collaborators"), () => HttpResponse.json(successEnvelope({ id: "c-new" }), { status: 201 })),
  http.delete(api("/projects/:id/collaborators/:userId"), () => HttpResponse.json(successEnvelope(null))),

  // Handover
  http.post(api("/projects/:id/handover-config"), () => HttpResponse.json(successEnvelope({ message: "Tersimpan" }))),

  // Activity log
  http.post(api("/activity-logs"), () => HttpResponse.json(successEnvelope(makeActivityLog()), { status: 201 })),
  http.post(api("/activity-logs/:id/polish"), () => HttpResponse.json(successEnvelope(makeActivityLog()))),
  http.get(api("/projects/:id/story"), () => HttpResponse.json(successEnvelope(makeStoryPage()))),

  // Calendar Sync
  http.get(api("/calendar/auth-url"), () =>
    HttpResponse.json(successEnvelope({ auth_url: "https://accounts.google.com/o/oauth2/auth?x=1" }))
  ),
  http.post(api("/calendar/map"), () => HttpResponse.json(successEnvelope({ id_log: "log-from-cal" }), { status: 201 })),
  http.get(GCAL_EVENTS_URL, () => HttpResponse.json({ items: [] })),
];

