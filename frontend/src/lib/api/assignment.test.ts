import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, successEnvelope, errorEnvelope } from "@/test";
import { assignProject, getAvailableSA, getPendingAssignment, reassignProject, reprovisionFolder } from "./assignment";

describe("assignment API", () => {
  it("getPendingAssignment mengembalikan daftar (kosong maupun terisi)", async () => {
    // Default global (grup shell) berisi satu proyek; test ini mulai dari keadaan kosong.
    server.use(http.get(api("/projects/pending-assignment"), () => HttpResponse.json(successEnvelope([]))));
    await expect(getPendingAssignment()).resolves.toEqual([]);
    server.use(http.get(api("/projects/pending-assignment"), () => HttpResponse.json(successEnvelope([{ id_project: "p1" }]))));
    await expect(getPendingAssignment()).resolves.toEqual([{ id_project: "p1" }]);
  });

  it("getPendingAssignment melempar ApiError saat error server", async () => {
    server.use(http.get(api("/projects/pending-assignment"), () => HttpResponse.json(errorEnvelope("Gagal"), { status: 500 })));
    await expect(getPendingAssignment()).rejects.toMatchObject({ status: 500, message: "Gagal" });
  });

  it("getAvailableSA mengambil SA beserta beban kerja", async () => {
    const sa = { id: "s1", name: "SA Satu", email: "a@b.c", avatar_url: null, active_project_count: 2 };
    server.use(http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([sa]))));
    await expect(getAvailableSA()).resolves.toEqual([sa]);
  });

  it("assignProject mem-POST sa_id ke proyek yang tepat", async () => {
    let body: unknown;
    let path = "";
    server.use(
      http.post(api("/projects/:id/assign"), async ({ request }) => {
        body = await request.json();
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope({ id_project: "p9", assigned_sa: "s1", assigned_at: "t", status: "Assigned" }));
      })
    );
    const res = await assignProject("p9", "s1");
    expect(path).toMatch(/\/projects\/p9\/assign$/);
    expect(body).toEqual({ sa_id: "s1" });
    expect(res.status).toBe("Assigned");
  });

  it("assignProject menolak dengan pesan backend (mis. 403 bukan Lead_SA)", async () => {
    server.use(http.post(api("/projects/:id/assign"), () => HttpResponse.json(errorEnvelope("Hanya Lead_SA"), { status: 403 })));
    await expect(assignProject("p9", "s1")).rejects.toMatchObject({ status: 403, message: "Hanya Lead_SA" });
  });

  it("reassignProject mem-POST sa_id baru ke endpoint reassign", async () => {
    let body: unknown;
    let path = "";
    server.use(
      http.post(api("/projects/:id/reassign"), async ({ request }) => {
        body = await request.json();
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope({ id_project: "p9", assigned_sa: "s2", assigned_sa_name: "SA Dua", status: "Assigned" }));
      })
    );
    await expect(reassignProject("p9", "s2")).resolves.toMatchObject({ assigned_sa_name: "SA Dua" });
    expect(path).toMatch(/\/projects\/p9\/reassign$/);
    expect(body).toEqual({ sa_id: "s2" });
  });

  it("reprovisionFolder mem-POST tanpa body dan mengembalikan status provisioning", async () => {
    let text = "bukan-kosong";
    server.use(
      http.post(api("/projects/:id/provision-folder"), async ({ request }) => {
        text = await request.text();
        return HttpResponse.json(successEnvelope({ id_project: "p9", folder_provisioning_status: "pending", folder_provisioning_triggered: true }));
      })
    );
    await expect(reprovisionFolder("p9")).resolves.toMatchObject({ folder_provisioning_triggered: true });
    expect(text).toBe("");
  });

  it("reprovisionFolder melempar error saat backend menolak", async () => {
    server.use(http.post(api("/projects/:id/provision-folder"), () => HttpResponse.json(errorEnvelope("Tidak boleh"), { status: 403 })));
    await expect(reprovisionFolder("p9")).rejects.toMatchObject({ status: 403 });
  });
});
