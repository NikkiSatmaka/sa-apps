/**
 * Perilaku aman-SSR: modul lib dipanggil di server (tanpa `window`) tidak boleh melempar
 * dan tidak boleh menyentuh storage/jaringan yang hanya ada di browser.
 */
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server, api, successEnvelope } from "@/test";
import { getNotifications } from "./api/notifications";
import { createProject } from "./api/projects";
import { apiRequest, fetcher } from "./fetcher";
import { logout } from "./auth";
import { enqueueSubmission, getQueuedItems, initOfflineSync, isOnline } from "./offline-queue";

describe("tanpa window (SSR)", () => {
  it("logout tidak melakukan apa pun", async () => {
    localStorage.setItem("access_token", "tok");
    const hit = vi.fn();
    server.use(http.post(api("/auth/logout"), () => { hit(); return HttpResponse.json({}); }));
    vi.stubGlobal("window", undefined);

    await expect(logout()).resolves.toBeUndefined();
    expect(hit).not.toHaveBeenCalled();
    expect(localStorage.getItem("access_token")).toBe("tok");
  });

  it("antrean offline: kosong, enqueue tidak menyimpan, init mengembalikan cleanup no-op", () => {
    vi.stubGlobal("window", undefined);
    expect(getQueuedItems()).toEqual([]);
    enqueueSubmission("http://x", "POST", {});
    expect(localStorage.length).toBe(0);
    expect(initOfflineSync()()).toBeUndefined();
  });

  it("isOnline dianggap true tanpa navigator", () => {
    vi.stubGlobal("navigator", undefined);
    expect(isOnline()).toBe(true);
  });

  it("klien API tidak mengirim Authorization (token tidak dibaca)", async () => {
    localStorage.setItem("access_token", "tok");
    const auths: (string | null)[] = [];
    server.use(
      http.get(api("/notifications"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json(successEnvelope({ items: [] }));
      }),
      http.post(api("/projects"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json(successEnvelope({}));
      }),
      http.post(api("/x"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json(successEnvelope({}));
      }),
      http.get(api("/y"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json(successEnvelope({}));
      })
    );
    vi.stubGlobal("window", undefined);

    await getNotifications();
    await createProject(new FormData());
    await apiRequest("/x", { body: 1 });
    await fetcher("/y");
    expect(auths).toEqual([null, null, null, null]);
  });

  it("fetcher 401 tanpa window tetap melempar ApiError tanpa menyentuh storage", async () => {
    localStorage.setItem("access_token", "tok");
    server.use(http.get(api("/z"), () => new HttpResponse(null, { status: 401 })));
    vi.stubGlobal("window", undefined);
    await expect(fetcher("/z")).rejects.toMatchObject({ status: 401, message: "Unauthorized" });
    expect(localStorage.getItem("access_token")).toBe("tok");
  });
});
