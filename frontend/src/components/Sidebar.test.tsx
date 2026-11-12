import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, setPathname, stubLocation } from "@/test";
import { server } from "@/test";
import { useAuthStore } from "@/store/auth";
import { useSidebarStore } from "@/store/sidebar";
import { Sidebar } from "./Sidebar";

function navLinks() {
  const nav = screen.getByRole("navigation");
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent?.trim());
}

describe("Sidebar — menu per peran", () => {
  it("Sales hanya melihat Dashboard, Proyek, Notifikasi (tanpa Activity Log dan menu Admin)", () => {
    renderWithProviders(<Sidebar />, { role: "Sales" });
    expect(navLinks()).toEqual(["Dashboard", "Proyek", "Notifikasi"]);
    expect(screen.queryByRole("link", { name: /settings|pengaturan|pengguna/i })).not.toBeInTheDocument();
  });

  it.each(["SA", "Lead_SA"] as const)("%s melihat semua menu umum tetapi bukan menu Admin", (role) => {
    renderWithProviders(<Sidebar />, { role });
    expect(navLinks()).toEqual(["Dashboard", "Proyek", "Activity Log", "Notifikasi"]);
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("Admin melihat menu umum plus bagian Admin dengan Pengguna, tanpa Pengaturan", () => {
    renderWithProviders(<Sidebar />, { role: "Admin" });
    expect(navLinks()).toEqual(["Dashboard", "Proyek", "Activity Log", "Notifikasi", "Pengguna"]);
    expect(screen.queryByRole("link", { name: /settings|pengaturan/i })).not.toBeInTheDocument();
    // Label bagian "Admin" (selain peran di footer) hanya ada untuk Admin
    expect(screen.getAllByText("Admin").some((el) => el.className.includes("uppercase"))).toBe(true);
    expect(screen.getByRole("link", { name: "Pengguna" })).toHaveAttribute("href", "/admin/users");
  });

  it("peran belum diketahui hanya menampilkan Dashboard dan Proyek", () => {
    renderWithProviders(<Sidebar />);
    expect(navLinks()).toEqual(["Dashboard", "Proyek"]);
  });
});

describe("Sidebar — interaksi", () => {
  it("menandai item aktif berdasarkan pathname (Dashboard hanya aktif di '/')", () => {
    setPathname("/projects/abc");
    renderWithProviders(<Sidebar />, { role: "SA" });
    const proyek = screen.getByRole("link", { name: "Proyek" });
    expect(proyek.className).toContain("bg-primary-50");
    expect(screen.getByRole("link", { name: "Dashboard" }).className).not.toContain("bg-primary-50");
  });

  it("menandai Dashboard aktif di '/' dan Pengguna aktif di /admin/users", () => {
    setPathname("/");
    const { unmount } = renderWithProviders(<Sidebar />, { role: "Admin" });
    expect(screen.getByRole("link", { name: "Dashboard" }).className).toContain("bg-primary-50");
    unmount();

    setPathname("/admin/users");
    renderWithProviders(<Sidebar />, { role: "Admin" });
    expect(screen.getByRole("link", { name: "Pengguna" }).className).toContain("bg-primary-50");
  });

  it("tombol toggle menciutkan sidebar: label teks hilang, lalu terbuka kembali", async () => {
    const { user } = renderWithProviders(<Sidebar />, { role: "Admin" });
    expect(screen.getByText("Portal SA")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tutup sidebar" }));
    expect(useSidebarStore.getState().isOpen).toBe(false);
    expect(screen.queryByText("Portal SA")).not.toBeInTheDocument();
    // Label item tidak tampil sebagai teks, tetapi link tetap dapat diakses lewat title
    expect(screen.queryByText("Notifikasi")).not.toBeInTheDocument();
    expect(screen.getByTitle("Notifikasi")).toBeInTheDocument();
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Buka sidebar" }));
    expect(screen.getByText("Portal SA")).toBeInTheDocument();
  });

  it("Keluar: membersihkan sesi, memanggil /auth/logout, dan mengarahkan ke /login", async () => {
    const loc = stubLocation();
    let logoutCalled = false;
    server.use(
      http.post(api("/auth/logout"), () => {
        logoutCalled = true;
        return HttpResponse.json({ status: "success", data: null, message: "ok" });
      }),
    );
    const { user } = renderWithProviders(<Sidebar />, { role: "SA" });

    await user.click(screen.getByRole("button", { name: "Keluar" }));

    await waitFor(() => expect(loc.href).toContain("/login"));
    expect(logoutCalled).toBe(true);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});
