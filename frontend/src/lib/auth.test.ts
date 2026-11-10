import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server, api, stubLocation } from "@/test";
import { logout } from "./auth";

describe("logout", () => {
  it("mencabut sesi di backend dengan Bearer token, hapus token, lalu redirect ke /login", async () => {
    localStorage.setItem("access_token", "tok");
    localStorage.setItem("refresh_token", "ref");
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
    expect(auth).toBe("Bearer tok");
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(loc.href).toBe("/login");
  });

  it("tanpa token: tidak memanggil backend tetapi tetap redirect", async () => {
    const loc = stubLocation();
    const hit = vi.fn();
    server.use(http.post(api("/auth/logout"), () => { hit(); return HttpResponse.json({}); }));

    await logout();

    expect(hit).not.toHaveBeenCalled();
    expect(loc.href).toBe("/login");
  });

  it("tetap logout lokal bila backend menolak (5xx)", async () => {
    localStorage.setItem("access_token", "tok");
    localStorage.setItem("refresh_token", "ref");
    const loc = stubLocation();
    server.use(http.post(api("/auth/logout"), () => new HttpResponse(null, { status: 500 })));

    await logout();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(loc.href).toBe("/login");
  });

  it("tetap logout lokal bila jaringan putus", async () => {
    localStorage.setItem("access_token", "tok");
    const loc = stubLocation();
    server.use(http.post(api("/auth/logout"), () => HttpResponse.error()));

    await logout();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(loc.href).toBe("/login");
  });
});
