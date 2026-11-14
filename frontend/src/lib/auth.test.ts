import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server, api, stubLocation } from "@/test";
import { getAccessToken, setAccessToken } from "@/lib/fetcher";
import { logout } from "./auth";

describe("logout", () => {
  it("mencabut sesi melalui cookie HttpOnly, menghapus token memory, lalu redirect ke /login", async () => {
    setAccessToken("tok");
    const loc = stubLocation();
    let auth: string | null = null;
    let method = "";
    server.use(
      http.post(api("/auth/logout"), ({ request }) => {
        auth = request.headers.get("Authorization");
        method = request.method;
        return HttpResponse.json({ status: "success" });
      })
    );

    await logout();

    expect(method).toBe("POST");
    expect(auth).toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(loc.href).toBe("/login");
  });

  it("tetap memanggil backend untuk menghapus cookie meski memory token kosong", async () => {
    const loc = stubLocation();
    const hit = vi.fn();
    server.use(http.post(api("/auth/logout"), () => { hit(); return HttpResponse.json({}); }));

    await logout();

    expect(hit).toHaveBeenCalledOnce();
    expect(loc.href).toBe("/login");
  });

  it("tetap logout lokal bila backend menolak (5xx)", async () => {
    setAccessToken("tok");
    const loc = stubLocation();
    server.use(http.post(api("/auth/logout"), () => new HttpResponse(null, { status: 500 })));

    await logout();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(loc.href).toBe("/login");
  });

  it("tetap logout lokal bila jaringan putus", async () => {
    setAccessToken("tok");
    const loc = stubLocation();
    server.use(http.post(api("/auth/logout"), () => HttpResponse.error()));

    await logout();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(loc.href).toBe("/login");
  });
});
