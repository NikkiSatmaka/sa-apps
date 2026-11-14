import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, gagalLaluBerhasil, renderWithProviders, router, server, successEnvelope } from "@/test";
import {
  makeAvailableSA,
  makeMonthlyUtilization,
  makePendingProject,
  makeProjectUtilization,
  makeUtilizationSummary,
} from "@/test/fixtures/shell";
import LeadSADashboard from "./page";

const ok = (path: string, data: unknown) =>
  server.use(http.get(api(path), () => HttpResponse.json(successEnvelope(data))));
const fail = (path: string, message = "boom", status = 500) =>
  server.use(http.get(api(path), () => HttpResponse.json({ status: "error", data: null, message }, { status })));
const hang = (path: string) => server.use(http.get(api(path), () => new Promise(() => {})));

const section = (name: string | RegExp) => screen.getByRole("heading", { name }).closest("section")!;

afterEach(() => vi.useRealTimers());

describe("Dashboard Lead SA — header", () => {
  it("menampilkan judul dan tombol Request SA yang membuka form baru", async () => {
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard Lead SA" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "+ Request SA" }));
    expect(router.push).toHaveBeenCalledWith("/projects/new");
  });
});

describe("Dashboard Lead SA — antrian assignment", () => {
  it("memuat: skeleton dan belum ada penghitung", () => {
    hang("/projects/pending-assignment");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Antrian Assignment");
    expect(s.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(within(s).queryByText(/menunggu/)).not.toBeInTheDocument();
  });

  it("kosong: pesan tidak ada proyek menunggu dan penghitung 0", async () => {
    ok("/projects/pending-assignment", []);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await screen.findByText("Tidak ada proyek yang menunggu assignment saat ini.")).toBeInTheDocument();
    expect(screen.getByText("0 menunggu")).toBeInTheDocument();
  });

  it("berisi: kartu proyek dengan BANT, tag (maks 3 + sisa), target, dan penghitung", async () => {
    ok("/projects/pending-assignment", [
      makePendingProject({ project_name: "Lulus", customer_name: "PT L", bant_score: 60, use_case_tags: ["a", "b", "c", "d", "e"] }),
      makePendingProject({ id_project: "p2", project_name: "Gagal", customer_name: "PT G", bant_score: 59, use_case_tags: [] }),
    ]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });

    expect(await screen.findByText("2 menunggu")).toBeInTheDocument();
    expect(screen.getByText("Lulus")).toBeInTheDocument();
    expect(screen.getByText("BANT Passed")).toBeInTheDocument();
    expect(screen.getByText("BANT not passed")).toBeInTheDocument();
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("c")).toBeInTheDocument();
    expect(screen.queryByText("d")).not.toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.getAllByText(/^Target:/)).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Assign SA" })).toHaveLength(2);
  });

  it.each([
    ["pending", "Folder Pending"],
    ["provisioned", "Folder Siap"],
    ["failed", "Provisioning Gagal"],
  ] as const)("status folder %s menampilkan badge '%s'", async (status, teks) => {
    ok("/projects/pending-assignment", [makePendingProject({ folder_provisioning_status: status })]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await screen.findByText(teks)).toBeInTheDocument();
  });

  it("status folder null: tanpa badge dan tanpa tombol provision", async () => {
    ok("/projects/pending-assignment", [makePendingProject({ folder_provisioning_status: null })]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    await screen.findByText("Proyek Antrian");
    expect(screen.queryByText(/Folder/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Provision Ulang" })).not.toBeInTheDocument();
  });

  it.each([
    ["Lead_SA", true],
    ["Admin", true],
    ["SA", false],
    ["Sales", false],
  ] as const)("tombol Provision Ulang untuk %s: %s", async (role, tampil) => {
    ok("/projects/pending-assignment", [makePendingProject({ folder_provisioning_status: "failed" })]);
    renderWithProviders(<LeadSADashboard />, { role });
    await screen.findByText("Provisioning Gagal");
    expect(!!screen.queryByRole("button", { name: "Provision Ulang" })).toBe(tampil);
  });

  it("Provision Ulang berhasil: memanggil endpoint, toast sukses, daftar dimuat ulang, toast hilang setelah 3 detik", async () => {
    let provisioned: string | null = null;
    let gets = 0;
    server.use(
      http.get(api("/projects/pending-assignment"), () => {
        gets++;
        return HttpResponse.json(successEnvelope([makePendingProject({ id_project: "pid", folder_provisioning_status: "failed" })]));
      }),
      http.post(api("/projects/:id/provision-folder"), ({ params }) => {
        provisioned = String(params.id);
        return HttpResponse.json(
          successEnvelope({ id_project: "pid", folder_provisioning_status: "pending", folder_provisioning_triggered: true }),
        );
      }),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    await user.click(await screen.findByRole("button", { name: "Provision Ulang" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Provisioning folder telah dijadwalkan ulang.");
    expect(provisioned).toBe("pid");
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));

    // Toast lokal hilang otomatis setelah 3 detik
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Provision Ulang gagal: toast error memuat pesan backend; tombol bisa ditutup manual", async () => {
    ok("/projects/pending-assignment", [makePendingProject({ folder_provisioning_status: "failed" })]);
    server.use(
      http.post(api("/projects/:id/provision-folder"), () =>
        HttpResponse.json({ status: "error", data: null, message: "Drive down" }, { status: 502 }),
      ),
    );
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Admin" });
    await user.click(await screen.findByRole("button", { name: "Provision Ulang" }));

    const toast = await screen.findByRole("alert");
    expect(toast).toHaveTextContent("Drive down");
    expect(toast.className).toContain("bg-red-50");
    await user.click(within(toast).getByRole("button", { name: "Tutup notifikasi" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Provision Ulang menonaktifkan tombol dan menampilkan 'Memproses…' selama berjalan", async () => {
    ok("/projects/pending-assignment", [makePendingProject({ folder_provisioning_status: "failed" })]);
    server.use(http.post(api("/projects/:id/provision-folder"), () => new Promise(() => {})));
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    await user.click(await screen.findByRole("button", { name: "Provision Ulang" }));
    expect(await screen.findByRole("button", { name: "Memproses…" })).toBeDisabled();
  });

  it("Assign SA membuka modal; Batal menutupnya", async () => {
    ok("/projects/pending-assignment", [makePendingProject({ project_name: "Buka Modal" })]);
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    await user.click(await screen.findByRole("button", { name: "Assign SA" }));
    expect(await screen.findByRole("heading", { name: "Assign SA ke Proyek" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("heading", { name: "Assign SA ke Proyek" })).not.toBeInTheDocument();
  });

  it("assignment berhasil: modal menutup, daftar dimuat ulang, toast sukses muncul lalu hilang", async () => {
    let gets = 0;
    let assigned: unknown = null;
    server.use(
      http.get(api("/projects/pending-assignment"), () => {
        gets++;
        return HttpResponse.json(successEnvelope([makePendingProject({ id_project: "pid" })]));
      }),
      http.post(api("/projects/:id/assign"), async ({ request, params }) => {
        assigned = { id: params.id, body: await request.json() };
        return HttpResponse.json(
          successEnvelope({ id_project: "pid", assigned_sa: "sa-1", assigned_at: "2025-01-01T00:00:00Z", status: "Assigned" }),
        );
      }),
    );
    ok("/sa/available", [makeAvailableSA({ id: "sa-1", name: "Rina" })]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });

    await user.click(await screen.findByRole("button", { name: "Assign SA" }));
    const modal = (await screen.findByRole("heading", { name: "Assign SA ke Proyek" })).closest("div.fixed")!;
    await user.click(await within(modal as HTMLElement).findByRole("button", { name: /Rina/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Assignment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SA berhasil ditugaskan ke proyek!");
    expect(screen.queryByRole("heading", { name: "Assign SA ke Proyek" })).not.toBeInTheDocument();
    expect(assigned).toEqual({ id: "pid", body: { sa_id: "sa-1", lead_sa_id: "00000000-0000-4000-8000-000000000003" } });
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Dashboard Lead SA — overview & utilisasi SA", () => {
  it("overview: skeleton, lalu total aktif dari ringkasan status", async () => {
    hang("/projects/status-summary");
    const { unmount } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(section("Overview Proyek Aktif").querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    unmount();

    ok("/projects/status-summary", [
      { status: "Assigned", count: 3 },
      { status: "Submitted", count: 2 },
      { status: "Status Aneh", count: 1 },
    ]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Overview Proyek Aktif");
    expect(await within(s).findByText("Total Aktif")).toBeInTheDocument();
    expect(within(s).getByText("6")).toBeInTheDocument();
    expect(within(s).getByText("Status Aneh")).toHaveClass("bg-neutral-100");
  });

  it("overview kosong", async () => {
    ok("/projects/status-summary", []);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await within(section("Overview Proyek Aktif")).findByText("Belum ada data proyek.")).toBeInTheDocument();
  });

  it("utilisasi SA: skeleton, kosong, dan daftar dengan avatar/inisial serta warna beban kerja", async () => {
    hang("/sa/available");
    const { unmount } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(section("Utilisasi SA").querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    unmount();

    ok("/sa/available", []);
    const kosong = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await within(section("Utilisasi SA")).findByText("Belum ada SA terdaftar.")).toBeInTheDocument();
    kosong.unmount();

    ok("/sa/available", [
      makeAvailableSA({ id: "a", name: "Ringan", active_project_count: 2, avatar_url: "http://localhost/a.png" }),
      makeAvailableSA({ id: "b", name: "Sedang", active_project_count: 4 }),
      makeAvailableSA({ id: "c", name: "Berat", active_project_count: 9 }),
    ]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Utilisasi SA");
    expect(await within(s).findByRole("img", { name: "Ringan" })).toHaveAttribute("src", "http://localhost/a.png");
    expect(within(s).getByText("S")).toBeInTheDocument(); // inisial tanpa avatar
    const bar = (nama: string) => within(s).getByText(nama).closest("div.flex")!.querySelector(".h-full") as HTMLElement;
    expect(bar("Ringan").className).toContain("bg-green-400");
    expect(bar("Sedang").className).toContain("bg-yellow-400");
    expect(bar("Berat").className).toContain("bg-red-400");
    expect(bar("Berat")).toHaveStyle({ width: "100%" });
  });
});

describe("Dashboard Lead SA — utilisasi per bulan", () => {
  it("memuat: skeleton tabel", () => {
    hang("/sa/utilization");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(section(/Utilisasi SA per Bulan/).querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("error: pesan gagal memuat beserta pesan server", async () => {
    fail("/sa/utilization", "Tabel rusak");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section(/Utilisasi SA per Bulan/);
    expect(await within(s).findByText(/Gagal memuat data utilisasi/)).toBeInTheDocument();
    expect(within(s).getByText("Tabel rusak")).toBeInTheDocument();
  });

  it("berisi: tabel per SA per bulan dengan total, ringkasan, dan sel kosong '-'", async () => {
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section(/Utilisasi SA per Bulan/);
    const table = await within(s).findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3); // header, 1 SA, total
    expect(within(rows[1]).getByText("SA Demo")).toBeInTheDocument();
    expect(within(rows[1]).getByText("80")).toBeInTheDocument();
    expect(within(rows[1]).getByText("150")).toBeInTheDocument();
    expect(within(rows[1]).getAllByText("-").length).toBe(8); // Mei–Des
    expect(within(rows[2]).getByText("Total")).toBeInTheDocument();
    expect(within(s).getByText(/150 jam/)).toHaveTextContent("150 jam");
    expect(within(s).getByText(/dari 1 SA/)).toBeInTheDocument();
    // warna heatmap mengikuti jam
    const sel = (jam: string) => within(rows[1]).getByText(jam).closest("td")!;
    expect(sel("5").className).toContain("bg-blue-50");
    expect(sel("20").className).toContain("bg-blue-100");
    expect(sel("45").className).toContain("bg-blue-200");
    expect(sel("80").className).toContain("bg-blue-300");
  });

  it("tanpa data aktivitas: pesan belum ada data untuk tahun terpilih", async () => {
    ok("/sa/utilization", makeMonthlyUtilization({ monthly_data: [] }));
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section(/Utilisasi SA per Bulan/);
    expect(await within(s).findByText(/Belum ada data activity log untuk tahun/)).toBeInTheDocument();
  });

  it("mengganti tahun dan SA meminta ulang data dengan parameter yang sesuai", async () => {
    const urls: string[] = [];
    server.use(
      http.get(api("/sa/utilization"), ({ request }) => {
        urls.push(new URL(request.url).search);
        return HttpResponse.json(successEnvelope(makeMonthlyUtilization()));
      }),
      // Default global /sa/available (grup operations) berisi SA lain; test ini butuh "SA Demo".
      http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([makeAvailableSA()]))),
    );
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const tahun = new Date().getFullYear();
    await screen.findByRole("table");
    expect(urls).toContain(`?year=${tahun}`);

    await user.selectOptions(document.getElementById("util-year") as HTMLSelectElement, String(tahun - 1));
    await waitFor(() => expect(urls).toContain(`?year=${tahun - 1}`));
    // filter tahun terhubung dengan seksi komposisi
    expect((document.getElementById("comp-year") as HTMLSelectElement).value).toBe(String(tahun - 1));

    const sa = document.getElementById("util-sa") as HTMLSelectElement;
    await waitFor(() => expect(within(sa).getByRole("option", { name: "SA Demo" })).toBeInTheDocument());
    await user.selectOptions(sa, "SA Demo");
    await waitFor(() =>
      expect(urls).toContain(`?year=${tahun - 1}&sa_id=00000000-0000-4000-8000-000000000002`),
    );
  });
});

describe("Dashboard Lead SA — komposisi utilisasi", () => {
  it("memuat: skeleton", () => {
    hang("/utilization/summary");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(section("Komposisi Utilisasi").querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("error: pesan gagal memuat komposisi", async () => {
    fail("/utilization/summary");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await within(section("Komposisi Utilisasi")).findByText("Gagal memuat komposisi utilisasi.")).toBeInTheDocument();
  });

  it("berisi: total Project/Non-Project, bar bulanan, dan rincian fase dengan persentase", async () => {
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Komposisi Utilisasi");
    expect(await within(s).findByText("Project vs Non-Project per Bulan")).toBeInTheDocument();
    expect(within(s).getByText("8 jam", { selector: "span.font-semibold" })).toBeInTheDocument();
    expect(within(s).getByText("2 jam", { selector: "span.font-semibold" })).toBeInTheDocument();
    expect(within(s).getByTitle("Jan: Project 8j, Non-Project 2j")).toBeInTheDocument();
    expect(within(s).getByText("Pre-Implementation")).toBeInTheDocument();
    expect(within(s).getAllByText("4 jam (50%)")).toHaveLength(2);
    expect(within(s).getByText("0 jam (0%)")).toBeInTheDocument(); // Post-Implementation
    expect(within(s).getByText("Total Project")).toBeInTheDocument();
  });

  it("tanpa data: pesan kosong untuk bar bulanan dan fase", async () => {
    ok(
      "/utilization/summary",
      makeUtilizationSummary({
        work_type: { months: {}, totals: { Project: 0, "Non-Project": 0 }, grand_total: 0 },
        project_phase: { totals: {}, total: 0 },
      }),
    );
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Komposisi Utilisasi");
    expect(await within(s).findByText(/Belum ada data activity log untuk tahun/)).toBeInTheDocument();
    expect(within(s).getByText("Belum ada aktivitas Project.")).toBeInTheDocument();
  });

  it("mengganti tahun lewat filter komposisi meminta ringkasan tahun itu", async () => {
    const years: string[] = [];
    server.use(
      http.get(api("/utilization/summary"), ({ request }) => {
        years.push(new URL(request.url).searchParams.get("year") ?? "");
        return HttpResponse.json(successEnvelope(makeUtilizationSummary()));
      }),
    );
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const tahun = new Date().getFullYear();
    await user.selectOptions(await screen.findByLabelText("Tahun", { selector: "#comp-year" }), String(tahun + 1));
    await waitFor(() => expect(years).toContain(String(tahun + 1)));
  });
});

describe("Dashboard Lead SA — effort per proyek", () => {
  it("memuat: skeleton", () => {
    hang("/utilization/projects");
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(section("Effort per Proyek").querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("kosong: pesan belum ada data per proyek", async () => {
    ok("/utilization/projects", []);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await within(section("Effort per Proyek")).findByText("Belum ada data activity log per proyek.")).toBeInTheDocument();
  });

  it("berisi: baris proyek dengan jam dan personel; klik baris membuka detail, link tidak menggandakan navigasi", async () => {
    ok("/utilization/projects", makeProjectUtilization());
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Effort per Proyek");
    const link = await within(s).findByRole("link", { name: "Proyek Effort" });
    expect(link).toHaveAttribute("href", "/projects/44444444-4444-4444-8444-444444444444");
    expect(within(s).getByText("PT Effort")).toBeInTheDocument();
    expect(within(s).getByText("(12 jam)")).toBeInTheDocument();

    await user.click(within(s).getByText("PT Effort"));
    expect(router.push).toHaveBeenCalledWith("/projects/44444444-4444-4444-8444-444444444444");

    router.push.mockClear();
    await user.click(link);
    expect(router.push).not.toHaveBeenCalled(); // stopPropagation: biarkan <Link> yang menavigasi
  });

  it("status proyek tak dikenal memakai gaya netral", async () => {
    ok("/utilization/projects", [{ ...makeProjectUtilization()[0], status: "Aneh" }]);
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(await within(section("Effort per Proyek")).findByText("Aneh")).toHaveClass("bg-neutral-100");
  });
});

describe("Dashboard Lead SA — error pemuatan dibedakan dari keadaan kosong (#82)", () => {
  it("antrian assignment: pesan error (bukan 'Tidak ada proyek'), penghitung tak tampil, coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/projects/pending-assignment", [makePendingProject({ project_name: "Pulih" })]));
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Antrian Assignment");

    expect(await within(s).findByRole("alert")).toHaveTextContent("Gagal memuat antrian assignment.");
    expect(within(s).queryByText("Tidak ada proyek yang menunggu assignment saat ini.")).not.toBeInTheDocument();
    expect(within(s).queryByText(/menunggu$/)).not.toBeInTheDocument();

    await user.click(within(s).getByRole("button", { name: "Coba lagi" }));

    expect(await within(s).findByText("Pulih")).toBeInTheDocument();
    expect(within(s).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("overview proyek aktif: pesan error (bukan 'Belum ada data proyek'), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/projects/status-summary", [{ status: "Assigned", count: 3 }]));
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Overview Proyek Aktif");

    expect(await within(s).findByRole("alert")).toHaveTextContent("Gagal memuat ringkasan proyek aktif.");
    expect(within(s).queryByText("Belum ada data proyek.")).not.toBeInTheDocument();

    await user.click(within(s).getByRole("button", { name: "Coba lagi" }));

    expect(await within(s).findByText("Total Aktif")).toBeInTheDocument();
  });

  it("utilisasi SA: pesan error (bukan 'Belum ada SA terdaftar'), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/sa/available", [makeAvailableSA({ name: "Pulih" })]));
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Utilisasi SA");

    expect(await within(s).findByRole("alert")).toHaveTextContent("Gagal memuat utilisasi SA.");
    expect(within(s).queryByText("Belum ada SA terdaftar.")).not.toBeInTheDocument();

    await user.click(within(s).getByRole("button", { name: "Coba lagi" }));

    expect(await within(s).findByText("Pulih")).toBeInTheDocument();
  });

  it("effort per proyek: pesan error (bukan 'Belum ada data activity log'), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/utilization/projects", makeProjectUtilization()));
    const { user } = renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    const s = section("Effort per Proyek");

    expect(await within(s).findByRole("alert")).toHaveTextContent("Gagal memuat effort per proyek.");
    expect(within(s).queryByText("Belum ada data activity log per proyek.")).not.toBeInTheDocument();

    await user.click(within(s).getByRole("button", { name: "Coba lagi" }));

    expect(await within(s).findByRole("link", { name: "Proyek Effort" })).toBeInTheDocument();
  });
});

describe("Dashboard Lead SA — tautan workload", () => {
  it("menampilkan tautan ke halaman workload", async () => {
    renderWithProviders(<LeadSADashboard />, { role: "Lead_SA" });
    expect(screen.getByRole("link", { name: "Lihat Workload" })).toHaveAttribute(
      "href",
      "/dashboard/lead-sa/workload",
    );
  });
});
