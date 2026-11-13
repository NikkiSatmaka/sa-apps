import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, server, stubLocation } from "@/test";
import { useAuthStore } from "@/store/auth";
import { UserMenu } from "./UserMenu";

describe("UserMenu", () => {
  it("tertutup secara default dan menampilkan inisial nama", () => {
    renderWithProviders(<UserMenu />, { role: "SA" });
    expect(screen.getByRole("button", { name: "Menu pengguna" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("S")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("membuka menu berisi nama, email, peran, link Profil Saya, dan tombol Keluar", async () => {
    const { user } = renderWithProviders(<UserMenu />, { role: "Lead_SA" });
    await user.click(screen.getByRole("button", { name: "Menu pengguna" }));

    const menu = screen.getByRole("menu");
    expect(menu).toHaveTextContent("Lead SA Demo");
    expect(menu).toHaveTextContent("lead@example.com");
    expect(menu).toHaveTextContent("Lead_SA");
    expect(screen.getByRole("menuitem", { name: "Profil Saya" })).toHaveAttribute("href", "/profile");
    expect(screen.getByRole("menuitem", { name: "Keluar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Menu pengguna" })).toHaveAttribute("aria-expanded", "true");
  });

  it("menutup menu dengan Escape, klik di luar, dan memilih item; klik di dalam menu tidak menutup", async () => {
    const { user } = renderWithProviders(
      <div>
        <p>Di luar</p>
        <UserMenu />
      </div>,
      { role: "Sales" },
    );
    const trigger = screen.getByRole("button", { name: "Menu pengguna" });

    await user.click(trigger);
    await user.keyboard("a"); // tombol selain Escape: tetap terbuka
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(screen.getByText("sales@example.com")); // di dalam menu
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.click(screen.getByText("Di luar"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(screen.getByRole("menuitem", { name: "Profil Saya" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger); // toggle buka lalu tutup
    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("showDetails menampilkan nama dan peran di samping avatar", () => {
    renderWithProviders(<UserMenu showDetails placement="up" align="left" className="x" />, { role: "Admin" });
    expect(screen.getByText("Admin Demo")).toBeInTheDocument();
    // Admin = flag pada role fungsional: label menampilkan keduanya
    expect(screen.getByText("SA · Admin")).toBeInTheDocument();
  });

  it("tanpa user: avatar 'U', nama 'User', peran '—'", async () => {
    const { user } = renderWithProviders(<UserMenu showDetails />);
    expect(screen.getByText("U")).toBeInTheDocument();
    expect(screen.getByText("User")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Menu pengguna" }));
    expect(screen.getAllByText("User").length).toBeGreaterThan(1);
  });

  it("Keluar membersihkan store, memanggil /auth/logout, dan mengarahkan ke /login", async () => {
    const loc = stubLocation();
    let logoutCalled = false;
    server.use(
      http.post(api("/auth/logout"), () => {
        logoutCalled = true;
        return HttpResponse.json({ status: "success", data: null, message: "ok" });
      }),
    );
    const { user } = renderWithProviders(<UserMenu />, { role: "SA" });
    await user.click(screen.getByRole("button", { name: "Menu pengguna" }));
    await user.click(screen.getByRole("menuitem", { name: "Keluar" }));

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(useAuthStore.getState().user).toBeNull();
    await waitFor(() => expect(loc.href).toContain("/login"));
    expect(logoutCalled).toBe(true);
  });
});
