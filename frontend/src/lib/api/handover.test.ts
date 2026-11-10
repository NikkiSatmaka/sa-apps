import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, successEnvelope, errorEnvelope } from "@/test";
import { getHandoverStatus, getRecommendations, setHandoverConfig, triggerHandover } from "./handover";

describe("handover API", () => {
  it("getRecommendations membuka envelope dan mengirim Bearer token", async () => {
    localStorage.setItem("access_token", "tok");
    let auth: string | null = null;
    const rec = { id_project: "p2", project_name: "X", doc_type: "HLD", use_case_tags: ["a"], gdrive_link: null, match_count: 2 };
    server.use(
      http.get(api("/projects/:id/recommendations"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope([rec]));
      })
    );
    await expect(getRecommendations("p1")).resolves.toEqual([rec]);
    expect(auth).toBe("Bearer tok");
  });

  it("tanpa token: tidak mengirim Authorization", async () => {
    let auth: string | null = "x";
    server.use(
      http.get(api("/projects/:id/recommendations"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope([]));
      })
    );
    await getRecommendations("p1");
    expect(auth).toBeNull();
  });

  it("getRecommendations: error dengan pesan backend", async () => {
    server.use(http.get(api("/projects/:id/recommendations"), () => HttpResponse.json(errorEnvelope("Tidak ada akses"), { status: 403 })));
    await expect(getRecommendations("p1")).rejects.toMatchObject({ name: "ApiError", status: 403, message: "Tidak ada akses" });
  });

  it("getRecommendations: error tanpa JSON memakai pesan bawaan dengan status", async () => {
    server.use(http.get(api("/projects/:id/recommendations"), () => new HttpResponse("oops", { status: 502 })));
    await expect(getRecommendations("p1")).rejects.toMatchObject({
      status: 502,
      message: "Gagal mengambil rekomendasi (status 502)",
    });
  });

  it("triggerHandover mem-POST dan mengembalikan hasil", async () => {
    let method = "";
    server.use(
      http.post(api("/projects/:id/handover"), ({ request }) => {
        method = request.method;
        return HttpResponse.json(successEnvelope({ status: "success", message: "OK", handover_folder_id: "f1" }));
      })
    );
    await expect(triggerHandover("p1")).resolves.toMatchObject({ handover_folder_id: "f1" });
    expect(method).toBe("POST");
  });

  it("triggerHandover: error 400 (belum siap) membawa pesan backend", async () => {
    server.use(http.post(api("/projects/:id/handover"), () => HttpResponse.json(errorEnvelope("HLD belum Final"), { status: 400 })));
    await expect(triggerHandover("p1")).rejects.toMatchObject({ status: 400, message: "HLD belum Final" });
  });

  it("triggerHandover: pesan bawaan saat body bukan JSON", async () => {
    server.use(http.post(api("/projects/:id/handover"), () => new HttpResponse("x", { status: 500 })));
    await expect(triggerHandover("p1")).rejects.toMatchObject({ message: "Gagal memproses handover (status 500)" });
  });

  it("getHandoverStatus mengembalikan kesiapan handover", async () => {
    server.use(
      http.get(api("/projects/:id/handover-status"), () =>
        HttpResponse.json(successEnvelope({ is_ready: false, has_hld_final: false, is_closed_win: true, pmo_email: null, delivery_email: null }))
      )
    );
    await expect(getHandoverStatus("p1")).resolves.toMatchObject({ is_ready: false, is_closed_win: true });
  });

  it("getHandoverStatus: error", async () => {
    server.use(http.get(api("/projects/:id/handover-status"), () => new HttpResponse("x", { status: 404 })));
    await expect(getHandoverStatus("p1")).rejects.toMatchObject({
      status: 404,
      message: "Gagal mengecek status handover (status 404)",
    });
  });

  it("setHandoverConfig mengirim email PMO dan Delivery (snake_case)", async () => {
    let body: unknown;
    server.use(
      http.post(api("/projects/:id/handover-config"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope({ message: "Tersimpan" }));
      })
    );
    await expect(setHandoverConfig("p1", "pmo@x.id", "del@x.id")).resolves.toEqual({ message: "Tersimpan" });
    expect(body).toEqual({ pmo_email: "pmo@x.id", delivery_email: "del@x.id" });
  });

  it("setHandoverConfig: error validasi 422", async () => {
    server.use(http.post(api("/projects/:id/handover-config"), () => HttpResponse.json(errorEnvelope("Email tidak valid"), { status: 422 })));
    await expect(setHandoverConfig("p1", "x", "y")).rejects.toMatchObject({ status: 422, message: "Email tidak valid" });
  });

  it("setHandoverConfig: pesan bawaan saat body bukan JSON", async () => {
    server.use(http.post(api("/projects/:id/handover-config"), () => new HttpResponse("x", { status: 500 })));
    await expect(setHandoverConfig("p1", "a", "b")).rejects.toMatchObject({
      message: "Gagal menyimpan konfigurasi handover (status 500)",
    });
  });
});

describe("handover API: respons tanpa envelope", () => {
  it("memakai body utuh bila tidak ada field `data`", async () => {
    server.use(
      http.get(api("/projects/:id/recommendations"), () => HttpResponse.json([{ id_project: "p2" }])),
      http.post(api("/projects/:id/handover"), () => HttpResponse.json({ status: "ok", message: "m" })),
      http.get(api("/projects/:id/handover-status"), () => HttpResponse.json({ is_ready: true })),
      http.post(api("/projects/:id/handover-config"), () => HttpResponse.json({ message: "ok" }))
    );
    await expect(getRecommendations("p")).resolves.toEqual([{ id_project: "p2" }]);
    await expect(triggerHandover("p")).resolves.toEqual({ status: "ok", message: "m" });
    await expect(getHandoverStatus("p")).resolves.toEqual({ is_ready: true });
    await expect(setHandoverConfig("p", "a", "b")).resolves.toEqual({ message: "ok" });
  });

  it("mengirim token untuk semua endpoint", async () => {
    localStorage.setItem("access_token", "tok");
    const auths: (string | null)[] = [];
    const rekam = ({ request }: { request: Request }) => {
      auths.push(request.headers.get("Authorization"));
      return HttpResponse.json(successEnvelope({}));
    };
    server.use(
      http.post(api("/projects/:id/handover"), rekam),
      http.get(api("/projects/:id/handover-status"), rekam),
      http.post(api("/projects/:id/handover-config"), rekam)
    );
    await triggerHandover("p");
    await getHandoverStatus("p");
    await setHandoverConfig("p", "a", "b");
    expect(auths).toEqual(["Bearer tok", "Bearer tok", "Bearer tok"]);
  });
});
