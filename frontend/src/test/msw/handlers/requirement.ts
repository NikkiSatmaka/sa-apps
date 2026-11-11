import { http, HttpResponse } from "msw";
import { makeRequirementDoc } from "../../fixtures/requirement";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

/**
 * Handler default grup Requirement/RAG (#67). Bentuk respons mengikuti backend:
 * - rekomendasi RAG: daftar di dalam `data` (dibaca `fetcher`);
 * - generate ulang / keep-version: 200 tanpa konten dipakai klien;
 * - butir Requirement: mengembalikan dokumen terbaru.
 * GET /projects/:id/documents dimiliki grup dokumen (documents.ts) — timpa per test lewat server.use.
 */
export const requirementHandlers = [
  http.get(api("/projects/:id/recommendations"), () => HttpResponse.json(successEnvelope([]))),
  http.post(api("/projects/:id/requirement/regenerate"), () =>
    HttpResponse.json(successEnvelope(null), { status: 202 })
  ),
  http.post(api("/projects/:id/requirement/keep-version"), () => HttpResponse.json(successEnvelope(null))),
  http.post(api("/projects/:id/requirement/items"), () =>
    HttpResponse.json(successEnvelope(makeRequirementDoc({ is_overridden: true })), { status: 201 })
  ),
  http.put(api("/projects/:id/requirement/items/:itemId"), () =>
    HttpResponse.json(successEnvelope(makeRequirementDoc({ is_overridden: true })))
  ),
  http.delete(api("/projects/:id/requirement/items/:itemId"), () =>
    HttpResponse.json(successEnvelope(makeRequirementDoc({ is_overridden: true })))
  ),
];
