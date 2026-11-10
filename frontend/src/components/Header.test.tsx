import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, setPathname } from "@/test";
import { useSidebarStore } from "@/store/sidebar";
import { Header } from "./Header";

describe("Header", () => {
  it("menampilkan breadcrumb, lonceng notifikasi, dan menu pengguna", async () => {
    setPathname("/projects");
    renderWithProviders(<Header />, { role: "Sales" });
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^Notifikasi/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Menu pengguna" })).toBeInTheDocument();
  });

  it("tombol 'Toggle navigasi' membuka/menutup sidebar lewat store", async () => {
    const { user } = renderWithProviders(<Header />, { role: "Sales" });
    expect(useSidebarStore.getState().isOpen).toBe(true);
    await user.click(screen.getByRole("button", { name: "Toggle navigasi" }));
    expect(useSidebarStore.getState().isOpen).toBe(false);
    await user.click(screen.getByRole("button", { name: "Toggle navigasi" }));
    expect(useSidebarStore.getState().isOpen).toBe(true);
  });
});
