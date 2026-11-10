import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders, setPathname } from "@/test";
import { Breadcrumb } from "./Breadcrumb";

const nav = () => screen.getByRole("navigation", { name: "Breadcrumb" });

describe("Breadcrumb", () => {
  it("di '/' menampilkan Portal SA (link ke '/') dan Dashboard sebagai halaman aktif", () => {
    setPathname("/");
    renderWithProviders(<Breadcrumb />);
    expect(within(nav()).getByRole("link", { name: "Portal SA" })).toHaveAttribute("href", "/");
    expect(within(nav()).getByText("Dashboard")).toHaveAttribute("aria-current", "page");
  });

  it("segmen perantara menjadi link dan segmen terakhir menjadi halaman aktif (bukan link)", () => {
    setPathname("/projects/new");
    renderWithProviders(<Breadcrumb />);
    expect(within(nav()).getByRole("link", { name: "Proyek" })).toHaveAttribute("href", "/projects");
    const aktif = within(nav()).getByText("Proyek Baru");
    expect(aktif).toHaveAttribute("aria-current", "page");
    expect(within(nav()).queryByRole("link", { name: "Proyek Baru" })).not.toBeInTheDocument();
  });

  it("segmen dinamis (id) diberi label 'Detail'", () => {
    setPathname("/projects/8f1c2d3e-aaaa-bbbb-cccc-111122223333/documents");
    renderWithProviders(<Breadcrumb />);
    expect(within(nav()).getByRole("link", { name: "Detail" })).toHaveAttribute(
      "href",
      "/projects/8f1c2d3e-aaaa-bbbb-cccc-111122223333",
    );
    expect(within(nav()).getByText("Dokumen")).toHaveAttribute("aria-current", "page");
  });

  it("/admin dan /dashboard tidak punya halaman sendiri sehingga ditampilkan sebagai teks biasa", () => {
    setPathname("/admin/settings");
    const { unmount } = renderWithProviders(<Breadcrumb />);
    expect(within(nav()).queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
    expect(within(nav()).getByText("Admin")).toBeInTheDocument();
    expect(within(nav()).getByText("Settings")).toHaveAttribute("aria-current", "page");
    unmount();

    setPathname("/dashboard/lead-sa");
    renderWithProviders(<Breadcrumb />);
    expect(within(nav()).queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(within(nav()).getByText("Lead SA")).toHaveAttribute("aria-current", "page");
  });
});
