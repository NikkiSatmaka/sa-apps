import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, seedAuth } from "@/test";
import { useAuthStore } from "@/store/auth";
import HomePage from "./page";

describe("HomePage — dashboard sesuai peran", () => {
  it("saat auth masih memuat menampilkan skeleton tanpa dashboard", () => {
    const { container } = renderWithProviders(<HomePage />);
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("isLoading true meski user ada tetap skeleton", () => {
    seedAuth("Sales");
    useAuthStore.getState().setLoading(true);
    renderWithProviders(<HomePage />);
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it.each([
    ["Sales", "Dashboard Sales"],
    ["SA", "Dashboard SA"],
    ["Lead_SA", "Dashboard Lead SA"],
    ["Admin", "Dashboard Lead SA"],
  ] as const)("peran %s melihat %s", async (role, judul) => {
    renderWithProviders(<HomePage />, { role });
    expect(await screen.findByRole("heading", { level: 1, name: judul })).toBeInTheDocument();
  });

  it("peran tak dikenal jatuh ke dashboard SA", async () => {
    seedAuth("SA", { role: "Tamu" as never });
    renderWithProviders(<HomePage />);
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard SA" })).toBeInTheDocument();
  });
});
