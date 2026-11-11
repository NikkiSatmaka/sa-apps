/**
 * Handler default untuk klien API di `src/lib/api/*` (tiket F2): assignment, bant-override,
 * handover, dokumen (mutasi/Requirement), dan proyek (BANT result, edit jawaban kuesioner).
 * Timpa per test dengan `server.use(...)` untuk menguji error atau memeriksa request.
 */
import { http, HttpResponse } from "msw";
import { makeDocument } from "../../fixtures/documents";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

export const libHandlers = [
  // assignment
  http.get(api("/projects/pending-assignment"), () => HttpResponse.json(successEnvelope([]))),
  http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([]))),
  http.post(api("/projects/:id/assign"), () =>
    HttpResponse.json(successEnvelope({ id_project: "p1", assigned_sa: "sa-1", assigned_at: "2025-01-01T00:00:00Z", status: "Assigned" }))
  ),
  http.post(api("/projects/:id/reassign"), () =>
    HttpResponse.json(successEnvelope({ id_project: "p1", assigned_sa: "sa-2", assigned_sa_name: "SA Dua", status: "Assigned" }))
  ),
  http.post(api("/projects/:id/provision-folder"), () =>
    HttpResponse.json(
      successEnvelope({ id_project: "p1", folder_provisioning_status: "pending", folder_provisioning_triggered: true })
    )
  ),

  // override skor BANT
  http.post(api("/projects/:id/score-manual"), () =>
    HttpResponse.json(
      successEnvelope({
        total_score: 80,
        sub_scores: { budget: 20, authority: 20, need: 20, timeline: 20 },
        status: "Pending Assignment",
      })
    )
  ),

  // handover & RAG
  http.get(api("/projects/:id/recommendations"), () => HttpResponse.json(successEnvelope([]))),
  http.post(api("/projects/:id/handover"), () =>
    HttpResponse.json(successEnvelope({ status: "success", message: "Handover berhasil" }))
  ),
  http.get(api("/projects/:id/handover-status"), () =>
    HttpResponse.json(
      successEnvelope({
        is_ready: true,
        has_hld_final: true,
        is_closed_win: true,
        pmo_email: "pmo@example.com",
        delivery_email: "delivery@example.com",
      })
    )
  ),
  http.post(api("/projects/:id/handover-config"), () => HttpResponse.json(successEnvelope({ message: "Tersimpan" }))),

  // dokumen (mutasi) & Requirement
  http.post(api("/projects/:id/documents"), () => HttpResponse.json(successEnvelope(makeDocument()), { status: 201 })),
  http.patch(api("/documents/:id/status"), () => HttpResponse.json(successEnvelope(makeDocument({ status: "Reviewed" })))),
  http.patch(api("/projects/:id/dq-number"), () =>
    HttpResponse.json(successEnvelope({ id_project: "p1", dq_number: "DQ-12345", status: "Active" }))
  ),
  http.get(api("/projects/:id/documents/solutions"), () => HttpResponse.json(successEnvelope([]))),
  http.post(api("/projects/:id/requirement/regenerate"), () => HttpResponse.json(successEnvelope(null))),
  http.post(api("/projects/:id/requirement/keep-version"), () => HttpResponse.json(successEnvelope(null))),
  http.post(api("/projects/:id/requirement/items"), () => HttpResponse.json(successEnvelope(makeDocument()))),
  http.put(api("/projects/:id/requirement/items/:itemId"), () => HttpResponse.json(successEnvelope(makeDocument()))),
  http.delete(api("/projects/:id/requirement/items/:itemId"), () => HttpResponse.json(successEnvelope(makeDocument()))),

  // proyek: hasil BANT & edit jawaban kuesioner
  http.get(api("/projects/:id/bant-result"), () =>
    HttpResponse.json(
      successEnvelope({
        bant_score: 80,
        bant_detail: { budget: 20, authority: 20, need: 20, timeline: 20 },
        use_case_tags: ["cloud"],
        status: "Pending Assignment",
      })
    )
  ),
  http.put(api("/projects/:id/qualification-answers"), () =>
    HttpResponse.json(successEnvelope({ total_score: 70, status: "Pending Assignment", rescored: true }))
  ),
];
