import { http, HttpResponse } from "msw";
import { successEnvelope } from "../../fixtures/envelope";
import { makeProjectDetail } from "../../fixtures/opportunity";
import { api } from "../base";

/**
 * Handler default F4: detail proyek untuk halaman edit, simpan metadata (PATCH), dan simpan
 * jawaban kuesioner (PUT). POST /projects ada di `projects.ts`; tiap test menimpanya sesuai skenario.
 */
export const opportunityHandlers = [
  http.get(api("/projects/:id"), () => HttpResponse.json(successEnvelope(makeProjectDetail()))),
  http.patch(api("/projects/:id"), () => HttpResponse.json(successEnvelope({ ok: true }))),
  http.put(api("/projects/:id/qualification-answers"), () =>
    HttpResponse.json(
      successEnvelope({ total_score: 72, status: "Awaiting Assignment", feedback: null, rescored: true }),
    ),
  ),
];
