import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, gagalLaluBerhasil, renderWithProviders, router, selaluGagal, server, successEnvelope } from "@/test";
import { makeSalesProject } from "@/test/fixtures/shell";
import SalesDashboard from "./page";

const projects = (data: unknown) => server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope(data))));
const summary = (data: unknown) =>
  server.use(http.get(api("/projects/status-summary"), () => HttpResponse.json(successEnvelope(data))));

describe("Dashboard requester (Sales dan Product)", () => {
  it("memuat: menampilkan skeleton (tanpa daftar maupun empty state)", () => {
    server.use(
      http.get(api("/projects"), () => new Promise(() => {})),
      http.get(api("/projects/status-summary"), () => new Promise(() => {})),
    );
    const { container } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard Requester" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(4);
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();
  });

  it("berisi: menampilkan ringkasan status dengan total dan kartu proyek", async () => {
    projects([
      makeSalesProject({ project_name: "Alpha", customer_name: "PT A", dq_number: null }),
      makeSalesProject({ id_project: "p2", project_name: "Beta", customer_name: "PT B", dq_number: "DQ-9", bant_score: 40 }),
    ]);
    renderWithProviders(<SalesDashboard />, { role: "Sales" });

    expect(await screen.findByRole("button", { name: "Proyek Alpha - PT A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Proyek Beta - PT B" })).toBeInTheDocument();
    expect(screen.getByText("Menunggu DQ")).toBeInTheDocument();
    expect(screen.getByText("DQ-9")).toBeInTheDocument();

    const overview = screen.getByRole("heading", { name: "Overview Proyek" }).closest("section")!;
    expect(await within(overview).findByText("Assigned")).toBeInTheDocument();
    expect(within(overview).getByText("Submitted")).toBeInTheDocument();
    expect(within(overview).getByText("5")).toBeInTheDocument(); // total 3 + 2
  });

  it.each(["Sales", "Product"] as const)("%s: meminta proyek terlibat (involved=me), diurutkan terbaru", async (role) => {
    const urls: string[] = [];
    server.use(
      http.get(api("/projects"), ({ request }) => {
        urls.push(new URL(request.url).search);
        return HttpResponse.json(successEnvelope([]));
      }),
      http.get(api("/projects/status-summary"), ({ request }) => {
        urls.push(new URL(request.url).search);
        return HttpResponse.json(successEnvelope([]));
      }),
    );
    renderWithProviders(<SalesDashboard />, { role });
    await screen.findByText("Belum ada proyek");
    expect(urls).toContain("?involved=me&sort=-updated_at");
    expect(urls).toContain("?involved=me");
    expect(urls.some((u) => u.includes("sales_pic"))).toBe(false);
  });

  it("kosong: empty state dan ringkasan kosong, CTA membuka form request baru", async () => {
    projects([]);
    summary([]);
    const { user } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    expect(await screen.findByText("Belum ada proyek")).toBeInTheDocument();
    expect(screen.getByText("Belum ada data proyek.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Request SA" }));
    expect(router.push).toHaveBeenCalledWith("/projects/new");
  });

  it("tombol '+ Request SA' di header membuka /projects/new", async () => {
    const { user } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    await user.click(screen.getByRole("button", { name: "+ Request SA" }));
    expect(router.push).toHaveBeenCalledWith("/projects/new");
  });

  it("klik kartu membuka detail proyek", async () => {
    projects([makeSalesProject({ id_project: "abc", project_name: "Gamma", customer_name: "PT G" })]);
    const { user } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    await user.click(await screen.findByRole("button", { name: "Proyek Gamma - PT G" }));
    expect(router.push).toHaveBeenCalledWith("/projects/abc");
  });

  it("tanpa user (auth belum siap) tidak meminta data apa pun", async () => {
    const dipanggil: string[] = [];
    server.use(
      http.get(api("/projects"), () => {
        dipanggil.push("projects");
        return HttpResponse.json(successEnvelope([]));
      }),
    );
    renderWithProviders(<SalesDashboard />);
    await new Promise((r) => setTimeout(r, 30));
    expect(dipanggil).toEqual([]);
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();
  });

  it("error memuat proyek: pesan error (bukan empty state) dan coba lagi memuat ulang daftar", async () => {
    server.use(gagalLaluBerhasil("/projects", [makeSalesProject({ project_name: "Pulih", customer_name: "PT P" })]));
    const { user } = renderWithProviders(<SalesDashboard />, { role: "Sales" });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar proyek.");
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByRole("button", { name: "Proyek Pulih - PT P" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("error memuat ringkasan: pesan error di bagian Overview (bukan 'Belum ada data'), bisa dicoba ulang", async () => {
    server.use(gagalLaluBerhasil("/projects/status-summary", [{ status: "Assigned", count: 3 }]));
    const { user } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    const overview = screen.getByRole("heading", { name: "Overview Proyek" }).closest("section")!;

    expect(await within(overview).findByRole("alert")).toHaveTextContent("Gagal memuat ringkasan proyek.");
    expect(within(overview).queryByText("Belum ada data proyek.")).not.toBeInTheDocument();

    await user.click(within(overview).getByRole("button", { name: "Coba lagi" }));

    expect(await within(overview).findByText("Assigned")).toBeInTheDocument();
    expect(within(overview).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("error di kedua permintaan: dua pesan error terpisah, tanpa empty state", async () => {
    server.use(selaluGagal("/projects"), selaluGagal("/projects/status-summary"));
    renderWithProviders(<SalesDashboard />, { role: "Sales" });

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();
    expect(screen.queryByText("Belum ada data proyek.")).not.toBeInTheDocument();
  });

  it("status tak dikenal tetap ditampilkan dengan gaya netral", async () => {
    summary([{ status: "Status Aneh", count: 1 }]);
    projects([]);
    renderWithProviders(<SalesDashboard />, { role: "Sales" });
    expect(await screen.findByText("Status Aneh")).toHaveClass("bg-neutral-100");
  });
});
