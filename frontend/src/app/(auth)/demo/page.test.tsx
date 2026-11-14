import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAuthStore } from "@/store/auth";
import { api, http, HttpResponse, renderWithProviders, router, server, setSearchParams } from "@/test";
import { authConfig } from "@/test/msw/handlers/auth-pages";
import { loginResponse, type Role } from "@/test/fixtures/users";
import { getAccessToken } from "@/lib/fetcher";
import DemoPage from "./page";

const roles: [Role, string][] = [
  ["Sales", "Login sebagai Sales"],
  ["Product", "Login sebagai Product Manager"],
  ["SA", "Login sebagai SA"],
  ["Lead_SA", "Login sebagai Lead SA"],
];

async function renderReady() {
  const utils = renderWithProviders(<DemoPage />);
  await screen.findByRole("button", { name: "Login sebagai Sales" });
  return utils;
}

describe("halaman /demo — guard demo mode", () => {
  it("memuat: hanya spinner (tanpa tombol) sebelum /auth/config terbaca", () => {
    renderWithProviders(<DemoPage />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Pilih role untuk demo login")).not.toBeInTheDocument();
  });

  it("demo_mode aktif: menampilkan empat role fungsional dan tautan ke /login", async () => {
    await renderReady();
    expect(screen.getByRole("status")).toHaveTextContent("Demo Mode");
    for (const [, label] of roles) expect(screen.getByRole("button", { name: label })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Login sebagai Admin" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Login dengan Google Account" })).toHaveAttribute("href", "/login");
    expect(router.replace).not.toHaveBeenCalled();
    for (const label of ["Sales 2 — Demo Sales 2", "Product Manager 2 — Demo Product 2", "SA 2 — Demo SA 2", "Lead SA 2 — Demo Lead SA 2", "Admin 2 — Demo Admin 2"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  it("demo_mode nonaktif: dialihkan ke /login dan tombol tidak pernah tampil", async () => {
    server.use(authConfig({ demo_mode: false }));
    renderWithProviders(<DemoPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("gagal memuat /auth/config: dianggap nonaktif → dialihkan ke /login", async () => {
    server.use(http.get(api("/auth/config"), () => HttpResponse.error()));
    renderWithProviders(<DemoPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("menampilkan pesan dari ?error=", async () => {
    setSearchParams({ error: "domain_not_allowed" });
    renderWithProviders(<DemoPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Domain email Anda tidak diizinkan");
  });

  it("?error tak dikenal memakai pesan generik", async () => {
    setSearchParams({ error: "xyz" });
    renderWithProviders(<DemoPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Terjadi kesalahan. Silakan coba lagi.");
  });
});

describe("halaman /demo — login per peran", () => {
  it.each(roles)("klik '%s' menyimpan token, mengisi store dengan peran tsb, dan menuju /", async (role, label) => {
    let body: unknown;
    server.use(
      http.post(api("/auth/demo-login"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(loginResponse(role));
      }),
    );
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: label }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(body).toEqual({ role });
    expect(getAccessToken()).toBe(`access-${role}`);
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    const dariBackend = loginResponse(role).user;
    expect(state.user).toMatchObject({
      role: dariBackend.role,
      is_admin: dariBackend.is_admin,
      full_name: dariBackend.name,
    });
  });

  it("keadaan memuat: tombol yang diklik menampilkan 'Memproses...' dan semua tombol dinonaktifkan", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(
      http.post(api("/auth/demo-login"), async () => {
        await gate;
        return HttpResponse.json(loginResponse("SA"));
      }),
    );
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai SA" }));

    expect(await screen.findByText("Memproses...")).toBeInTheDocument();
    for (const b of screen.getAllByRole("button")) expect(b).toBeDisabled();

    release();
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("Memproses...")).not.toBeInTheDocument();
  });

  it("respons gagal dengan pesan: menampilkan pesan backend, tidak menyimpan token, tidak berpindah", async () => {
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.json({ message: "Demo dinonaktifkan" }, { status: 403 })));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai Sales" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Demo dinonaktifkan");
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Login sebagai Sales" })).toBeEnabled(); // bisa dicoba lagi
  });

  it("respons gagal tanpa JSON: pesan generik berisi kode status", async () => {
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.text("oops", { status: 500 })));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai SA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Login gagal (500)");
  });

  it("error jaringan: menampilkan pesan error dan kembali ke keadaan siap", async () => {
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.error()));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai Sales" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.queryByText("Memproses...")).not.toBeInTheDocument();
  });

  it("login ulang setelah gagal menghapus pesan error sebelumnya", async () => {
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.json({ message: "Gagal sementara" }, { status: 500 }), { once: true }));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai SA" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Login sebagai SA" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("menerima bentuk respons lain: { data: { tokens, user } } dan { access_token, user } datar", async () => {
    const r = loginResponse("Lead_SA");
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.json({ data: r }), { once: true }));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai Lead SA" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(getAccessToken()).toBe("access-Lead_SA");
    expect(useAuthStore.getState().user?.role).toBe("Lead_SA");

    localStorage.clear();
    router.push.mockClear();
    server.use(
      http.post(api("/auth/demo-login"), () => HttpResponse.json({ access_token: "flat-token", user: r.user }), { once: true }),
    );
    await user.click(screen.getByRole("button", { name: "Login sebagai Lead SA" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(getAccessToken()).toBe("flat-token");
    expect(localStorage.getItem("refresh_token")).toBeNull(); // tidak ada refresh_token → tidak disimpan
  });

  it("respons tanpa user: token tersimpan dan berpindah, tetapi store tidak terisi (perilaku nyata)", async () => {
    server.use(http.post(api("/auth/demo-login"), () => HttpResponse.json({ tokens: { access_token: "t" } })));
    const { user } = await renderReady();
    await user.click(screen.getByRole("button", { name: "Login sebagai SA" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(getAccessToken()).toBe("t");
    expect(useAuthStore.getState().user).toBeNull();
  });
});
