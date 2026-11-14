import { describe, expect, it } from "vitest";
import { setAccessToken } from "@/lib/fetcher";
import { getAccessToken } from "@/lib/fetcher";
import { http, HttpResponse, server, api, successEnvelope, errorEnvelope, stubLocation } from "@/test";
import { makeNotification, makePaginatedNotifications } from "@/test/fixtures/notifications";
import { getNotifications, getUnreadCount, markAsRead } from "./notifications";

describe("getNotifications", () => {
  it("default halaman 1 dengan 20 per halaman", async () => {
    let search = "";
    server.use(
      http.get(api("/notifications"), ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json(successEnvelope(makePaginatedNotifications([makeNotification()])));
      })
    );
    const res = await getNotifications();
    expect(search).toBe("?page=1&per_page=20");
    expect(res.items).toHaveLength(1);
  });

  it("meneruskan nomor halaman dan menyertakan token", async () => {
    setAccessToken("tok");
    let search = "";
    let auth: string | null = null;
    server.use(
      http.get(api("/notifications"), ({ request }) => {
        search = new URL(request.url).search;
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(makePaginatedNotifications([])));
      })
    );
    const res = await getNotifications(3);
    expect(search).toBe("?page=3&per_page=20");
    expect(auth).toBe("Bearer tok");
    expect(res.items).toEqual([]); // keadaan kosong
  });

  it("error: pesan backend, lalu pesan bawaan", async () => {
    server.use(http.get(api("/notifications"), () => HttpResponse.json(errorEnvelope("Akses ditolak"), { status: 403 })));
    // 401 pada GET kini ditangani terpusat (lihat blok "penanganan 401"); pesan backend diuji dengan 403.
    await expect(getNotifications()).rejects.toMatchObject({ status: 403, message: "Akses ditolak" });
    server.use(http.get(api("/notifications"), () => new HttpResponse("x", { status: 500 })));
    await expect(getNotifications()).rejects.toMatchObject({ message: "Gagal mengambil notifikasi (status 500)" });
  });
});

describe("markAsRead", () => {
  it("PATCH ke notifikasi yang tepat dan tidak mengembalikan nilai", async () => {
    let method = "";
    let path = "";
    server.use(
      http.patch(api("/notifications/:id/read"), ({ request }) => {
        method = request.method;
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope(null));
      })
    );
    await expect(markAsRead("n-7")).resolves.toBeUndefined();
    expect(method).toBe("PATCH");
    expect(path).toMatch(/\/notifications\/n-7\/read$/);
  });

  it("error: pesan backend, lalu pesan bawaan", async () => {
    server.use(http.patch(api("/notifications/:id/read"), () => HttpResponse.json(errorEnvelope("Bukan milik Anda"), { status: 403 })));
    await expect(markAsRead("n-7")).rejects.toMatchObject({ status: 403, message: "Bukan milik Anda" });
    server.use(http.patch(api("/notifications/:id/read"), () => new HttpResponse("x", { status: 500 })));
    await expect(markAsRead("n-7")).rejects.toMatchObject({ message: "Gagal menandai notifikasi (status 500)" });
  });
});

describe("getUnreadCount", () => {
  it("mengembalikan jumlah belum dibaca (termasuk nol)", async () => {
    server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json(successEnvelope({ count: 0 }))));
    await expect(getUnreadCount()).resolves.toEqual({ count: 0 });
    server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json(successEnvelope({ count: 4 }))));
    await expect(getUnreadCount()).resolves.toEqual({ count: 4 });
  });

  it("error: pesan backend, lalu pesan bawaan", async () => {
    server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json(errorEnvelope("Gagal"), { status: 500 })));
    await expect(getUnreadCount()).rejects.toMatchObject({ message: "Gagal" });
    server.use(http.get(api("/notifications/unread-count"), () => new HttpResponse("x", { status: 503 })));
    await expect(getUnreadCount()).rejects.toMatchObject({ message: "Gagal mengambil unread count (status 503)" });
  });
});

describe("notifications API: token dan respons tanpa envelope", () => {
  it("markAsRead dan getUnreadCount menyertakan token; body tanpa envelope dipakai utuh", async () => {
    setAccessToken("tok");
    const auths: (string | null)[] = [];
    server.use(
      http.patch(api("/notifications/:id/read"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json(successEnvelope(null));
      }),
      http.get(api("/notifications/unread-count"), ({ request }) => {
        auths.push(request.headers.get("Authorization"));
        return HttpResponse.json({ count: 2 });
      })
    );
    await markAsRead("n1");
    await expect(getUnreadCount()).resolves.toEqual({ count: 2 });
    expect(auths).toEqual(["Bearer tok", "Bearer tok"]);
  });

  it("getNotifications memakai body utuh bila tanpa `data`", async () => {
    server.use(http.get(api("/notifications"), () => HttpResponse.json({ items: [], total: 0 })));
    await expect(getNotifications()).resolves.toEqual({ items: [], total: 0 });
  });
});

describe("notifications: penanganan 401 lewat fetcher (#83)", () => {
  it("GET 401: hapus kedua token, arahkan ke /login, lempar ApiError 401 (sama dengan fetcher)", async () => {
    setAccessToken("a");
    localStorage.setItem("refresh_token", "r");
    const loc = stubLocation();
    server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json(errorEnvelope("Token kadaluarsa"), { status: 401 })));

    await expect(getUnreadCount()).rejects.toMatchObject({ name: "ApiError", status: 401, message: "Unauthorized" });
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(loc.href).toBe("/login");
  });

  it("mutasi 401: hanya ApiError dengan pesan backend, token tetap (sama dengan apiRequest)", async () => {
    setAccessToken("a");
    const loc = stubLocation();
    server.use(http.patch(api("/notifications/n1/read"), () => HttpResponse.json(errorEnvelope("Token kadaluarsa"), { status: 401 })));

    await expect(markAsRead("n1")).rejects.toMatchObject({ status: 401, message: "Token kadaluarsa" });
    expect(getAccessToken()).toBe("a");
    expect(loc.href).toBe("http://localhost/");
  });
});
