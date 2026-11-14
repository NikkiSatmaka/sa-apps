import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, gagalLaluBerhasil, renderWithProviders, router, selaluGagal, server, successEnvelope } from "@/test";
import { makeTugasSaya } from "@/test/fixtures/project-detail";
import { makeSAProject } from "@/test/fixtures/shell";
import SADashboard from "./page";

const projects = (data: unknown) => server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope(data))));

describe("Dashboard SA", () => {
  it("memuat: skeleton tanpa empty state", () => {
    server.use(
      http.get(api("/projects"), () => new Promise(() => {})),
      http.get(api("/projects/status-summary"), () => new Promise(() => {})),
    );
    const { container } = renderWithProviders(<SADashboard />, { role: "SA" });
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(4);
    expect(screen.queryByText(/Belum ada proyek yang ditugaskan/)).not.toBeInTheDocument();
  });

  it("meminta proyek yang melibatkan SA (involved=me, terbaru dulu)", async () => {
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
    renderWithProviders(<SADashboard />, { role: "SA" });
    await screen.findByText(/Belum ada proyek yang ditugaskan/);
    expect(urls).toContain("?involved=me&sort=-updated_at");
    expect(urls).toContain("?involved=me");
  });

  it("kosong: pesan belum ada proyek dan ringkasan kosong", async () => {
    projects([]);
    server.use(http.get(api("/projects/status-summary"), () => HttpResponse.json(successEnvelope([]))));
    renderWithProviders(<SADashboard />, { role: "SA" });
    expect(await screen.findByText("Belum ada proyek yang ditugaskan kepada Anda.")).toBeInTheDocument();
    expect(await screen.findByText("Belum ada data proyek.")).toBeInTheDocument();
  });

  it("berisi: kartu menampilkan status, progres dokumen, tanggal, dan menandai total ringkasan", async () => {
    projects([
      makeSAProject({ project_name: "Proyek A", customer_name: "PT A", doc_final_count: 2, doc_total_count: 4 }),
      makeSAProject({ id_project: "p2", project_name: "Proyek B", customer_name: "PT B", doc_final_count: 3, doc_total_count: 3, status: "Submitted" }),
      makeSAProject({ id_project: "p3", project_name: "Proyek C", customer_name: "PT C", doc_final_count: 0, doc_total_count: 0, status: "Lost" }),
    ]);
    renderWithProviders(<SADashboard />, { role: "SA" });

    const a = await screen.findByRole("article", { name: "Proyek Proyek A - PT A" });
    expect(within(a).getByText("2/4 Final")).toBeInTheDocument();
    expect(within(a).getByRole("progressbar", { name: "Progres dokumen: 2/4 Final" })).toHaveStyle({ width: "50%" });
    expect(within(a).getByText("Assigned")).toBeInTheDocument();
    expect(within(a).getByText(/Update:/)).toHaveTextContent("2025");

    const b = screen.getByRole("article", { name: "Proyek Proyek B - PT B" });
    expect(within(b).getByRole("progressbar")).toHaveStyle({ width: "100%" });
    const c = screen.getByRole("article", { name: "Proyek Proyek C - PT C" });
    expect(within(c).getByText("Belum ada dokumen")).toBeInTheDocument();
    expect(within(c).getByRole("progressbar")).toHaveStyle({ width: "0%" });

    const overview = screen.getByRole("heading", { name: "Overview Proyek" }).closest("section")!;
    expect(await within(overview).findByText("Total")).toBeInTheDocument();
    expect(within(overview).getByText("5")).toBeInTheDocument();
  });

  it("badge 'Menunggu DQ' dan SLA hanya saat DQ Number belum diinput", async () => {
    projects([
      makeSAProject({ project_name: "Tanpa DQ", customer_name: "PT X", dq_number: null, sla_days_elapsed: 2 }),
      makeSAProject({ id_project: "p2", project_name: "Dengan DQ", customer_name: "PT Y", dq_number: "DQ-1", sla_days_elapsed: 2 }),
    ]);
    renderWithProviders(<SADashboard />, { role: "SA" });
    const tanpa = await screen.findByRole("article", { name: "Proyek Tanpa DQ - PT X" });
    expect(within(tanpa).getByText("Menunggu DQ")).toBeInTheDocument();
    const dengan = screen.getByRole("article", { name: "Proyek Dengan DQ - PT Y" });
    expect(within(dengan).queryByText("Menunggu DQ")).not.toBeInTheDocument();
    // Kartu tanpa DQ memuat badge SLA tambahan (lebih banyak teks status-badge)
    expect(tanpa.querySelectorAll("span").length).toBeGreaterThan(dengan.querySelectorAll("span").length);
  });

  it("navigasi: judul ke detail, Activity Log, Documents, dan tombol Request SA", async () => {
    projects([makeSAProject({ id_project: "xyz", project_name: "Nav", customer_name: "PT N" })]);
    const { user } = renderWithProviders(<SADashboard />, { role: "SA" });

    await user.click(await screen.findByRole("heading", { name: "Nav" }));
    expect(router.push).toHaveBeenLastCalledWith("/projects/xyz");
    await user.click(screen.getByRole("button", { name: "Activity Log proyek Nav" }));
    expect(router.push).toHaveBeenLastCalledWith("/activity-logs?project=xyz");
    await user.click(screen.getByRole("button", { name: "Documents proyek Nav" }));
    expect(router.push).toHaveBeenLastCalledWith("/projects/xyz/documents");
    await user.click(screen.getByRole("button", { name: "+ Request SA" }));
    expect(router.push).toHaveBeenLastCalledWith("/projects/new");
  });

  it("warna badge status mengikuti status proyek", async () => {
    projects(
      ["Assigned", "Submitted", "Won", "Handed Over", "Lost", "Lainnya"].map((status, i) =>
        makeSAProject({ id_project: `p${i}`, project_name: `P${i}`, customer_name: "C", status }),
      ),
    );
    renderWithProviders(<SADashboard />, { role: "SA" });
    await screen.findByRole("article", { name: "Proyek P0 - C" });
    const warna = (i: number, teks: string) =>
      within(screen.getByRole("article", { name: `Proyek P${i} - C` })).getByText(teks).className;
    expect(warna(1, "Submitted")).toContain("bg-green-100");
    expect(warna(2, "Won")).toContain("bg-emerald-100");
    expect(warna(3, "Handed Over")).toContain("bg-teal-100");
    expect(warna(4, "Lost")).toContain("bg-red-100");
    expect(warna(5, "Lainnya")).toContain("bg-neutral-100");
  });

  it("error memuat proyek: pesan error (bukan empty state), coba lagi memuat ulang daftar", async () => {
    server.use(gagalLaluBerhasil("/projects", [makeSAProject({ project_name: "Pulih", customer_name: "PT P" })]));
    const { user } = renderWithProviders(<SADashboard />, { role: "SA" });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar proyek.");
    expect(screen.queryByText(/Belum ada proyek/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByRole("article", { name: "Proyek Pulih - PT P" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("error memuat ringkasan: pesan error di Overview (bukan 'Belum ada data'), bisa dicoba ulang", async () => {
    server.use(gagalLaluBerhasil("/projects/status-summary", [{ status: "Assigned", count: 3 }]));
    const { user } = renderWithProviders(<SADashboard />, { role: "SA" });
    const overview = screen.getByRole("heading", { name: "Overview Proyek" }).closest("section")!;

    expect(await within(overview).findByRole("alert")).toHaveTextContent("Gagal memuat ringkasan proyek.");
    expect(within(overview).queryByText("Belum ada data proyek.")).not.toBeInTheDocument();

    await user.click(within(overview).getByRole("button", { name: "Coba lagi" }));

    expect(await within(overview).findByText("Assigned")).toBeInTheDocument();
  });

  it("error di kedua permintaan: dua pesan error terpisah", async () => {
    server.use(selaluGagal("/projects"), selaluGagal("/projects/status-summary"));
    renderWithProviders(<SADashboard />, { role: "SA" });

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.queryByText(/Belum ada proyek/)).not.toBeInTheDocument();
  });

  it("menampilkan section 'Tugas saya' dengan subtask lintas project", async () => {
    projects([]);
    server.use(
      http.get(api("/projects/status-summary"), () => HttpResponse.json(successEnvelope([]))),
      http.get(api("/subtasks/saya"), () =>
        HttpResponse.json(successEnvelope({ items: [makeTugasSaya({ title: "Tugas dari dashboard" })], total: 1 })),
      ),
    );
    renderWithProviders(<SADashboard />, { role: "SA" });
    expect(await screen.findByRole("heading", { name: "Tugas Saya" })).toBeInTheDocument();
    expect(await screen.findByText("Tugas dari dashboard")).toBeInTheDocument();
  });
});
