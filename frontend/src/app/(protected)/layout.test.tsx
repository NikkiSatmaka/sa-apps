import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, http, HttpResponse, renderWithProviders, router, server } from "@/test";
import type { Role } from "@/test/fixtures/users";
import ProtectedLayout from "./layout";

const renderLayout = (role?: Role) =>
  renderWithProviders(
    <ProtectedLayout>
      <p>Isi halaman</p>
    </ProtectedLayout>,
    { role },
  );

describe("layout (protected)", () => {
  it("tanpa login: dialihkan ke /login dan tidak ada sidebar, header, maupun konten", async () => {
    renderLayout();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Isi halaman")).not.toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("token ditolak: shell tidak pernah dirender", async () => {
    localStorage.setItem("access_token", "kedaluwarsa");
    renderLayout();
    expect(screen.getByText("Memuat...")).toBeInTheDocument();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
  });

  it.each(["Sales", "SA", "Lead_SA", "Admin"] as const)("peran %s: header, sidebar navigasi, dan konten utama tampil", async (role) => {
    renderLayout(role);
    const main = await screen.findByRole("main");
    expect(within(main).getByText("Isi halaman")).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation").length).toBeGreaterThan(0);
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("memvalidasi sesi lewat /auth/me saat belum ada user di store", async () => {
    let calls = 0;
    server.use(
      http.get(api("/auth/me"), () => {
        calls += 1;
        return HttpResponse.json({ id: "1", email: "sa@example.com", name: "SA Demo", role: "SA", avatar_url: null });
      }),
    );
    localStorage.setItem("access_token", "access-SA");
    renderLayout();
    expect(await screen.findByRole("main")).toBeInTheDocument();
    expect(calls).toBe(1);
  });
});
