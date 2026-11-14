import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/store/auth";
import { api, http, HttpResponse, renderWithProviders, router, server, setSearchParams } from "@/test";
import { loginResponse, backendUser } from "@/test/fixtures/users";
import AuthCallbackPage from "./page";
import { getAccessToken } from "@/lib/fetcher";

/** Bentuk fragment persis seperti yang dibuat proxy `api/v1/[...path]`. */
function proxyFragment(role: "SA" | "Admin" | "Product" = "SA") {
  const { user, tokens } = loginResponse(role);
  return `#${new URLSearchParams({
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    user: encodeURIComponent(JSON.stringify(user)),
  })}`;
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  window.history.replaceState(null, "", "/auth/callback");
});

describe("halaman /auth/callback — menolak token fragment legacy", () => {
  it("tidak mempercayai access/refresh token pada fragment", async () => {
    window.location.hash = proxyFragment("SA");
    renderWithProviders(<AuthCallbackPage />);
    expect(screen.getByText("Memproses login...")).toBeInTheDocument();

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("token dibersihkan dari URL (hash dihapus) setelah diproses", async () => {
    window.location.hash = proxyFragment("Admin");
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("access-Admin");
    // Persona Admin = SA dengan is_admin (ADR 0012)
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("tanpa handoff code tidak memproses token fragment", async () => {
    const { user } = loginResponse("SA");
    window.location.hash = `#${new URLSearchParams({ access_token: "solo", user: encodeURIComponent(JSON.stringify(user)) })}`;
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
  });

  it("parameter user rusak (bukan JSON): ke /login?error=auth_failed dan tidak ada token tersimpan", async () => {
    window.location.hash = "#access_token=abc&user=%7Brusak";
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("tidak menerima user yang ditanam di fragment", async () => {
    const user = { id: "u", email: "x@y.z", full_name: "Nama Penuh", role: "SA" };
    window.location.hash = `#${new URLSearchParams({ access_token: "a", user: encodeURIComponent(JSON.stringify(user)) })}`;
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("halaman /auth/callback — error & tanpa data", () => {
  it("?error= dari Google → /login?error=auth_cancelled", async () => {
    setSearchParams({ error: "access_denied" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_cancelled"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("tanpa token maupun code → /login?error=auth_failed", async () => {
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
  });

  it("hash tanpa parameter user dianggap tidak ada token → auth_failed", async () => {
    window.location.hash = "#access_token=saja";
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});

describe("halaman /auth/callback — jalur fallback ?code=", () => {
  it("menukar handoff dengan POST, memasang access token di memory, tanpa localStorage", async () => {
    localStorage.clear();
    let exchangeCalled = false;
    server.use(
      http.post(api("/auth/callback/exchange"), () => {
        exchangeCalled = true;
        return HttpResponse.json({ user: backendUser("SA"), access_token: "memory-access", expires_in: 900 });
      },
      ),
    );
    setSearchParams({ code: "handoff-once" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
    expect(exchangeCalled).toBe(true);
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("code valid: POST handoff exchange, memasang token memory, mengisi store, menuju /", async () => {
    setSearchParams({ code: "kode-ok" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
    expect(getAccessToken()).toBe("access-SA");
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().user).toMatchObject({ role: "SA", full_name: backendUser("SA").name });
  });

  it("backend 403 → /login?error=domain_not_allowed", async () => {
    setSearchParams({ code: "forbidden" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=domain_not_allowed"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("backend 500 → /login?error=auth_failed", async () => {
    setSearchParams({ code: "broken" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("respons sukses berbentuk aneh (tanpa tokens) → auth_failed, bukan crash", async () => {
    server.use(http.post(api("/auth/callback/exchange"), () => HttpResponse.json({ foo: 1 })));
    setSearchParams({ code: "apa-saja" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("error jaringan → auth_failed", async () => {
    server.use(http.post(api("/auth/callback/exchange"), () => HttpResponse.error()));
    setSearchParams({ code: "x" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=auth_failed"));
  });

  it("hanya diproses sekali (guard double-effect): navigasi tepat satu kali", async () => {
    setSearchParams({ code: "kode-ok" });
    renderWithProviders(<AuthCallbackPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(router.replace).toHaveBeenCalledTimes(1);
  });
});
