import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, router, server, successEnvelope } from "@/test";
import { makeSalesProject } from "@/test/fixtures/shell";
import SalesDashboard from "./page";

const projects = (data: unknown) => server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope(data))));
const summary = (data: unknown) =>
  server.use(http.get(api("/projects/status-summary"), () => HttpResponse.json(successEnvelope(data))));

describe("Dashboard Sales", () => {
  it("memuat: menampilkan skeleton (tanpa daftar maupun empty state)", () => {
    server.use(
      http.get(api("/projects"), () => new Promise(() => {})),
      http.get(api("/projects/status-summary"), () => new Promise(() => {})),
    );
    const { container } = renderWithProviders(<SalesDashboard />, { role: "Sales" });
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard Sales" })).toBeInTheDocument();
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
    expect(within(overview).getByText("Ready")).toBeInTheDocument();
    expect(within(overview).getByText("5")).toBeInTheDocument(); // total 3 + 2
  });

  it("meminta data milik Sales sendiri, diurutkan terbaru", async () => {
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
    renderWithProviders(<SalesDashboard />, { role: "Sales" });
    await screen.findByText("Belum ada proyek");
    expect(urls).toContain("?sales_pic=me&sort=-updated_at");
    expect(urls).toContain("?sales_pic=me");
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

  it("error: halaman tidak menampilkan data maupun empty state (tidak ada UI error khusus)", async () => {
    // Perilaku nyata: dashboard Sales tidak punya keadaan error; hanya header yang tersisa.
    server.use(
      http.get(api("/projects"), () => HttpResponse.json({ message: "boom" }, { status: 500 })),
      http.get(api("/projects/status-summary"), () => HttpResponse.json({ message: "boom" }, { status: 500 })),
    );
    renderWithProviders(<SalesDashboard />, { role: "Sales" });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard Sales" })).toBeInTheDocument();
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();
    expect(screen.queryByText("Belum ada data proyek.")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("status tak dikenal tetap ditampilkan dengan gaya netral", async () => {
    summary([{ status: "Status Aneh", count: 1 }]);
    projects([]);
    renderWithProviders(<SalesDashboard />, { role: "Sales" });
    expect(await screen.findByText("Status Aneh")).toHaveClass("bg-neutral-100");
  });
});
