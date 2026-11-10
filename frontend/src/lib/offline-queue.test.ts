import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server, setOnline } from "@/test";
import {
  dequeueSubmission,
  enqueueSubmission,
  getQueuedItems,
  initOfflineSync,
  isOnline,
  submitWithOfflineSupport,
  syncOfflineQueue,
} from "./offline-queue";

const KEY = "portal-sa-offline-queue";
const URL_API = "http://localhost/api/v1/activity-logs";

beforeEach(() => {
  // Lacak event pembaruan antrean agar UI-indikator bisa bereaksi
  vi.spyOn(window, "dispatchEvent");
});

const eventsDiterbitkan = () =>
  vi.mocked(window.dispatchEvent).mock.calls.filter(([e]) => e.type === "offline-queue-updated").length;

describe("enqueue / getQueuedItems / dequeue", () => {
  it("antrean awal kosong", () => {
    expect(getQueuedItems()).toEqual([]);
  });

  it("enqueue menyimpan item lengkap, menambah header JSON default, dan memberi tahu UI", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-06-01T00:00:00Z"));

    const item = enqueueSubmission(URL_API, "POST", { a: 1 }, { "X-Test": "1" }, "Activity Log");

    expect(item).toMatchObject({
      url: URL_API,
      method: "POST",
      body: '{"a":1}',
      headers: { "Content-Type": "application/json", "X-Test": "1" },
      retryCount: 0,
      description: "Activity Log",
      createdAt: new Date("2025-06-01T00:00:00Z").getTime(),
    });
    expect(item.id).toMatch(/^oq-/);
    expect(getQueuedItems()).toEqual([item]);
    expect(eventsDiterbitkan()).toBe(1);
  });

  it("deskripsi default 'Submission' dan urutan FIFO dipertahankan; id unik", () => {
    const a = enqueueSubmission(URL_API, "POST", 1);
    const b = enqueueSubmission(URL_API, "PUT", 2);
    expect(a.description).toBe("Submission");
    expect(a.id).not.toBe(b.id);
    expect(getQueuedItems().map((i) => i.method)).toEqual(["POST", "PUT"]);
  });

  it("dequeue menghapus hanya item itu dan memberi tahu UI; id tak dikenal diabaikan", () => {
    const a = enqueueSubmission(URL_API, "POST", 1);
    const b = enqueueSubmission(URL_API, "POST", 2);
    vi.mocked(window.dispatchEvent).mockClear();

    dequeueSubmission(a.id);
    expect(getQueuedItems()).toEqual([b]);
    expect(eventsDiterbitkan()).toBe(1);

    dequeueSubmission("tidak-ada");
    expect(getQueuedItems()).toEqual([b]);
  });

  it("storage rusak → antrean dianggap kosong, enqueue tetap bisa menimpa", () => {
    localStorage.setItem(KEY, "{rusak");
    expect(getQueuedItems()).toEqual([]);
    enqueueSubmission(URL_API, "POST", 1);
    expect(getQueuedItems()).toHaveLength(1);
  });

  it("antrean bertahan antar pemanggilan (persisten di localStorage)", () => {
    enqueueSubmission(URL_API, "PATCH", { x: 1 });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toHaveLength(1);
  });
});

describe("isOnline", () => {
  it("mengikuti navigator.onLine", () => {
    setOnline(false, false);
    expect(isOnline()).toBe(false);
    setOnline(true, false);
    expect(isOnline()).toBe(true);
  });
});

describe("syncOfflineQueue", () => {
  it("offline: tidak mengirim apa pun dan antrean utuh", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    setOnline(false, false);
    const hit = vi.fn();
    server.use(http.post(URL_API, () => { hit(); return HttpResponse.json({}); }));

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 0, failed: 0 });
    expect(hit).not.toHaveBeenCalled();
    expect(getQueuedItems()).toHaveLength(1);
  });

  it("antrean kosong: tidak ada yang disinkronkan", async () => {
    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 0, failed: 0 });
  });

  it("sukses: mengirim method/header/body asli lalu mengosongkan antrean", async () => {
    enqueueSubmission(URL_API, "POST", { catatan: "halo" }, { Authorization: "Bearer t" });
    let diterima: { body: unknown; auth: string | null; method: string } | undefined;
    server.use(
      http.post(URL_API, async ({ request }) => {
        diterima = { body: await request.json(), auth: request.headers.get("Authorization"), method: request.method };
        return HttpResponse.json({ ok: true }, { status: 201 });
      })
    );

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 1, failed: 0 });
    expect(diterima).toEqual({ body: { catatan: "halo" }, auth: "Bearer t", method: "POST" });
    expect(getQueuedItems()).toEqual([]);
  });

  it("error klien 4xx dibuang dari antrean (tidak akan pernah berhasil) dan dihitung synced", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    server.use(http.post(URL_API, () => HttpResponse.json({}, { status: 422 })));

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 1, failed: 0 });
    expect(getQueuedItems()).toEqual([]);
  });

  it("error server 5xx: tetap di antrean dengan retryCount bertambah; percobaan ulang berhasil", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    server.use(http.post(URL_API, () => new HttpResponse(null, { status: 503 })));

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 0, failed: 1 });
    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 0, failed: 1 });
    expect(getQueuedItems()[0].retryCount).toBe(2);

    server.use(http.post(URL_API, () => HttpResponse.json({})));
    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 1, failed: 0 });
    expect(getQueuedItems()).toEqual([]);
  });

  it("jaringan putus: item tetap dan retryCount bertambah", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    server.use(http.post(URL_API, () => HttpResponse.error()));

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 0, failed: 1 });
    expect(getQueuedItems()[0].retryCount).toBe(1);
  });

  it("campuran: item gagal tidak menghalangi item lain; hanya yang gagal tersisa", async () => {
    enqueueSubmission(URL_API + "/a", "POST", "a");
    enqueueSubmission(URL_API + "/b", "POST", "b");
    enqueueSubmission(URL_API + "/c", "POST", "c");
    server.use(
      http.post(URL_API + "/a", () => HttpResponse.json({})),
      http.post(URL_API + "/b", () => new HttpResponse(null, { status: 500 })),
      http.post(URL_API + "/c", () => HttpResponse.json({}))
    );

    await expect(syncOfflineQueue()).resolves.toEqual({ synced: 2, failed: 1 });
    const sisa = getQueuedItems();
    expect(sisa).toHaveLength(1);
    expect(sisa[0].url).toBe(URL_API + "/b");
  });

  it("memberi tahu UI setelah sinkronisasi", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    server.use(http.post(URL_API, () => HttpResponse.json({})));
    vi.mocked(window.dispatchEvent).mockClear();
    await syncOfflineQueue();
    expect(eventsDiterbitkan()).toBeGreaterThanOrEqual(1);
  });
});

describe("submitWithOfflineSupport", () => {
  it("online: langsung kirim JSON dan kembalikan response, tidak masuk antrean", async () => {
    let diterima: unknown;
    server.use(
      http.post(URL_API, async ({ request }) => {
        diterima = { body: await request.json(), ct: request.headers.get("Content-Type"), x: request.headers.get("X-A") };
        return HttpResponse.json({ ok: true });
      })
    );
    const res = await submitWithOfflineSupport(URL_API, "POST", { a: 1 }, { headers: { "X-A": "1" } });

    expect(res.queued).toBe(false);
    expect(res.response?.ok).toBe(true);
    expect(diterima).toEqual({ body: { a: 1 }, ct: "application/json", x: "1" });
    expect(getQueuedItems()).toEqual([]);
  });

  it("response error server tidak diantrekan (dikembalikan ke pemanggil)", async () => {
    server.use(http.post(URL_API, () => new HttpResponse(null, { status: 500 })));
    const res = await submitWithOfflineSupport(URL_API, "POST", {});
    expect(res.queued).toBe(false);
    expect(res.response?.status).toBe(500);
    expect(getQueuedItems()).toEqual([]);
  });

  it("offline: langsung diantrekan dengan deskripsi dan tanpa request", async () => {
    setOnline(false, false);
    const hit = vi.fn();
    server.use(http.post(URL_API, () => { hit(); return HttpResponse.json({}); }));

    const res = await submitWithOfflineSupport(URL_API, "POST", { a: 1 }, { description: "Activity Log: Meeting" });

    expect(res).toEqual({ queued: true });
    expect(hit).not.toHaveBeenCalled();
    expect(getQueuedItems()).toMatchObject([{ url: URL_API, description: "Activity Log: Meeting", body: '{"a":1}' }]);
  });

  it("online tetapi koneksi putus di tengah jalan: diantrekan", async () => {
    server.use(http.put(URL_API, () => HttpResponse.error()));
    const res = await submitWithOfflineSupport(URL_API, "PUT", { a: 1 });
    expect(res).toEqual({ queued: true });
    expect(getQueuedItems()).toMatchObject([{ method: "PUT", description: "Submission" }]);
  });
});

describe("initOfflineSync", () => {
  let cleanup: (() => void) | undefined;
  afterEach(() => cleanup?.());

  it("saat event online: menyinkronkan antrean yang tertunda (alur offline → online)", async () => {
    setOnline(false, false);
    await submitWithOfflineSupport(URL_API, "POST", { a: 1 });
    expect(getQueuedItems()).toHaveLength(1);
    let dikirim = 0;
    server.use(http.post(URL_API, () => { dikirim++; return HttpResponse.json({}); }));

    cleanup = initOfflineSync();
    expect(dikirim).toBe(0); // offline: belum ada sync awal

    setOnline(true); // memicu event "online"
    await vi.waitFor(() => expect(getQueuedItems()).toEqual([]));
    expect(dikirim).toBe(1);
  });

  it("sync awal saat init bila sudah online dan ada item tertunda", async () => {
    enqueueSubmission(URL_API, "POST", 1);
    server.use(http.post(URL_API, () => HttpResponse.json({})));

    cleanup = initOfflineSync();
    await vi.waitFor(() => expect(getQueuedItems()).toEqual([]));
  });

  it("tanpa item tertunda: tidak ada request saat init", () => {
    const hit = vi.fn();
    server.use(http.post(URL_API, () => { hit(); return HttpResponse.json({}); }));
    cleanup = initOfflineSync();
    expect(hit).not.toHaveBeenCalled();
  });

  it("cleanup melepas listener: event online berikutnya tidak menyinkronkan", async () => {
    const stop = initOfflineSync();
    stop();
    enqueueSubmission(URL_API, "POST", 1);
    const hit = vi.fn();
    server.use(http.post(URL_API, () => { hit(); return HttpResponse.json({}); }));

    setOnline(true);
    await new Promise((r) => setTimeout(r, 20));
    expect(hit).not.toHaveBeenCalled();
    expect(getQueuedItems()).toHaveLength(1);
  });

  describe("Background Sync (bila didukung browser)", () => {
    const pasang = (ready: Promise<unknown>) => {
      vi.stubGlobal("SyncManager", class {});
      Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { ready } });
    };
    afterEach(() => {
      // @ts-expect-error — hapus stub properti navigator
      delete navigator.serviceWorker;
    });

    it("mendaftarkan tag sync-offline-submissions", async () => {
      const register = vi.fn().mockResolvedValue(undefined);
      pasang(Promise.resolve({ sync: { register } }));
      cleanup = initOfflineSync();
      await vi.waitFor(() => expect(register).toHaveBeenCalledWith("sync-offline-submissions"));
    });

    it("kegagalan pendaftaran ditelan (fallback ke event online)", async () => {
      const register = vi.fn().mockRejectedValue(new Error("tidak tersedia"));
      pasang(Promise.resolve({ sync: { register } }));
      cleanup = initOfflineSync();
      await vi.waitFor(() => expect(register).toHaveBeenCalled());
    });
  });
});
