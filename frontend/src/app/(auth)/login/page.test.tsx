import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, http, HttpResponse, renderWithProviders, server, setSearchParams, stubLocation } from "@/test";
import { authConfig } from "@/test/msw/handlers/auth-pages";
import LoginPage from "./page";

describe("halaman /login", () => {
  it("menampilkan judul dan tombol Google nonaktif sebelum konfigurasi OAuth terbaca", () => {
    server.use(authConfig({ oauth_configured: true }));
    renderWithProviders(<LoginPage />);
    expect(screen.getByRole("heading", { name: "Portal SA" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Google OAuth \(Belum dikonfigurasi\)/ })).toBeDisabled();
  });

  it("OAuth terkonfigurasi: tombol aktif dan klik mengarahkan browser ke /auth/login backend", async () => {
    server.use(authConfig({ oauth_configured: true, demo_mode: false }));
    const loc = stubLocation();
    const { user } = renderWithProviders(<LoginPage />);
    const button = await screen.findByRole("button", { name: "Login dengan Google" });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(loc.href).toBe(api("/auth/login"));
  });

  it("OAuth belum dikonfigurasi: tombol tetap nonaktif dan ada petunjuk hubungi administrator", async () => {
    server.use(authConfig({ oauth_configured: false }));
    renderWithProviders(<LoginPage />);
    expect(await screen.findByText(/Hubungi administrator/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Belum dikonfigurasi/ })).toBeDisabled();
  });

  it("tautan demo hanya muncul bila backend mengaktifkan demo_mode", async () => {
    server.use(authConfig({ oauth_configured: true, demo_mode: true }));
    renderWithProviders(<LoginPage />);
    const link = await screen.findByRole("link", { name: "Masuk ke mode demo" });
    expect(link).toHaveAttribute("href", "/demo");
  });

  it("demo_mode nonaktif: tidak ada tautan demo", async () => {
    server.use(authConfig({ oauth_configured: true, demo_mode: false }));
    renderWithProviders(<LoginPage />);
    await screen.findByRole("button", { name: "Login dengan Google" });
    expect(screen.queryByRole("link", { name: /demo/i })).not.toBeInTheDocument();
  });

  it("gagal memuat /auth/config: halaman tetap tampil dengan tombol nonaktif, tanpa tautan demo", async () => {
    server.use(http.get(api("/auth/config"), () => HttpResponse.error()));
    renderWithProviders(<LoginPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Belum dikonfigurasi/ })).toBeDisabled());
    expect(screen.queryByRole("link", { name: /demo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["domain_not_allowed", "Domain email Anda tidak diizinkan untuk mengakses sistem ini."],
    ["auth_cancelled", "Login dibatalkan."],
    ["auth_failed", "Login gagal. Silakan coba lagi."],
    ["sesuatu_lain", "Terjadi kesalahan. Silakan coba lagi."],
  ])("query ?error=%s menampilkan pesan yang sesuai", async (code, pesan) => {
    server.use(authConfig({ oauth_configured: true }));
    setSearchParams({ error: code });
    renderWithProviders(<LoginPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(pesan);
    await screen.findByRole("button", { name: "Login dengan Google" });
  });

  it("tanpa ?error tidak ada alert", async () => {
    server.use(authConfig({ oauth_configured: true }));
    renderWithProviders(<LoginPage />);
    await screen.findByRole("button", { name: "Login dengan Google" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
