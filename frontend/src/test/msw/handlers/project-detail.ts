/** Handler default grup detail proyek (#66): detail, story, subtask, tim SA, SA tersedia, handover-status, hapus, override BANT. */
import { http, HttpResponse } from "msw";
import { makeProjectDetail, makeTimSA } from "../../fixtures/project-detail";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

export const projectDetailHandlers = [
  http.get(api("/projects/:id"), () => HttpResponse.json(successEnvelope(makeProjectDetail()))),
  http.get(api("/projects/:id/story"), () => HttpResponse.json(successEnvelope({ items: [], total: 0 }))),
  http.get(api("/projects/:id/subtasks"), () => HttpResponse.json(successEnvelope({ items: [], total: 0 }))),
  http.get(api("/projects/:id/comments"), () => HttpResponse.json(successEnvelope({ items: [], total: 0 }))),
  http.get(api("/projects/:id/tim-sa"), () => HttpResponse.json(successEnvelope(makeTimSA()))),
  http.get(api("/projects/:id/handover-status"), () =>
    HttpResponse.json(successEnvelope({ is_ready: true, has_hld_final: true, is_closed_win: true, pmo_email: "pmo@example.com", delivery_email: "delivery@example.com" })),
  ),
  http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([]))),
  http.delete(api("/projects/:id"), () => HttpResponse.json(successEnvelope(null))),
  http.post(api("/projects/:id/score-manual"), () =>
    HttpResponse.json(successEnvelope({ total_score: 72, sub_scores: { budget: 18, authority: 18, need: 18, timeline: 18 }, status: "Awaiting Assignment" })),
  ),
];
