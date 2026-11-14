import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, seedAuth, server, successEnvelope } from "@/test";
import WorkloadPage from "./page";

const URL = {
  beban: "/workload/beban",
  dueDate: "/workload/jatuh-tempo",
  macet: "/workload/macet",
  aksi: "/workload/butuh-aksi",
};

const beban = {
  minggu_mulai: "2030-01-07",
  items: [
    { user_id: "u1", name: "Ani SA", email: "ani@x.id", role: "SA", project_aktif: 3, subtask_aktif: 5, jam_minggu_ini: 12.5 },
    { user_id: "u2", name: "Budi Lead", email: "budi@x.id", role: "Lead_SA", project_aktif: 0, subtask_aktif: 0, jam_minggu_ini: 0 },
  ],
};

const dueDate = {
  hari_peringatan: 3,
  subtask: [
    { id_subtask: "ST-1", id_project: "P1", project_name: "Proyek Alfa", title: "Susun BoQ", status: "open", assigned_sa: "u1", assigned_sa_name: "Ani SA", due_date: "2030-01-05", hari_lagi: -2, terlambat: true },
    { id_subtask: "ST-2", id_project: "P1", project_name: "Proyek Alfa", title: "Review HLD", status: "in_progress", assigned_sa: null, assigned_sa_name: null, due_date: "2030-01-07", hari_lagi: 0, terlambat: false },
    { id_subtask: "ST-3", id_project: "P2", project_name: "Proyek Beta", title: "Demo", status: "open", assigned_sa: "u2", assigned_sa_name: "Budi Lead", due_date: "2030-01-10", hari_lagi: 3, terlambat: false },
  ],
  project: [
    { id_project: "P9", project_name: "Proyek Telat", customer_name: "PT Telat", status: "In Progress", target_submit: "2030-01-06", hari_lagi: -1, terlambat: true },
  ],
};

const macet = {
  ambang_hari: { "In Progress": 14 },
  items: [
    { id_project: "P5", project_name: "Proyek Macet", customer_name: "PT Macet", status: "In Progress", masuk_status_sejak: "2029-12-20T00:00:00Z", hari_di_status: 18, ambang_hari: 14, sumber: "audit" },
  ],
};

const aksi = {
  items: [
    { jenis: "awaiting_assignment", id_project: "A1", project_name: "Proyek Antri", customer_name: "PT A", status: "Awaiting Assignment", qualification_state: "Qualified" },
    { jenis: "dq_kosong", id_project: "A2", project_name: "Proyek Tanpa DQ", customer_name: "PT B", status: "Assigned", qualification_state: "Qualified" },
    { jenis: "need_clarification", id_project: "A3", project_name: "Proyek Klarifikasi", customer_name: "PT C", status: "Intake", qualification_state: "Need Clarification" },
  ],
};

const ok = (path: string, data: unknown) =>
  server.use(http.get(api(path), () => HttpResponse.json(successEnvelope(data))));
const fail = (path: string) =>
  server.use(http.get(api(path), () => HttpResponse.json({ status: "error", data: null, message: "boom" }, { status: 500 })));
const hang = (path: string) => server.use(http.get(api(path), () => new Promise(() => {})));
const isiSemua = () => {
  ok(URL.beban, beban);
  ok(URL.dueDate, dueDate);
  ok(URL.macet, macet);
  ok(URL.aksi, aksi);
};
const section = (name: string) => screen.getByRole("heading", { name }).closest("section")!;

describe("Workload Lead_SA — akses", () => {
  it.each(["SA", "Sales", "Product"] as const)("%s ditolak: pesan akses dan tidak ada request", async (role) => {
    const diminta = vi.fn();
    for (const path of Object.values(URL)) {
      server.use(http.get(api(path), () => { diminta(path); return HttpResponse.json(successEnvelope({})); }));
    }
    renderWithProviders(<WorkloadPage />, { role });
    expect(await screen.findByText("Halaman ini hanya untuk Lead_SA atau Admin.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Beban SA" })).not.toBeInTheDocument();
    expect(diminta).not.toHaveBeenCalled();
  });

  it.each([
    ["Lead_SA", undefined],
    ["SA", { is_admin: true }],
  ] as const)("%s (override %j) melihat keempat tampilan", async (role, override) => {
    isiSemua();
    seedAuth(role, override);
    renderWithProviders(<WorkloadPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "Workload SA" })).toBeInTheDocument();
    for (const nama of ["Beban SA", "Due Date", "Project Macet", "Butuh Aksi"]) {
      expect(screen.getByRole("heading", { name: nama })).toBeInTheDocument();
    }
  });
});

describe("Workload Lead_SA — isi", () => {
  it("beban: tabel per SA dengan project, subtask, dan jam minggu ini", async () => {
    isiSemua();
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    const baris = (await within(section("Beban SA")).findByText("Ani SA")).closest("tr")!;
    expect(within(baris).getByText("SA")).toBeInTheDocument();
    expect(within(baris).getByText("3")).toBeInTheDocument();
    expect(within(baris).getByText("5")).toBeInTheDocument();
    expect(within(baris).getByText("12,5 jam")).toBeInTheDocument();
    const lead = within(section("Beban SA")).getByText("Budi Lead").closest("tr")!;
    expect(within(lead).getByText("0 jam")).toBeInTheDocument();
  });

  it("due date: subtask dan project dengan penanda terlambat, hari ini, dan H-n", async () => {
    isiSemua();
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    const s = section("Due Date");
    expect(await within(s).findByText("Susun BoQ")).toBeInTheDocument();
    expect(within(s).getByText("Terlambat 2 hari")).toBeInTheDocument();
    expect(within(s).getByText("Hari ini")).toBeInTheDocument();
    expect(within(s).getByText("H-3")).toBeInTheDocument();
    expect(within(s).getByText("Terlambat 1 hari")).toBeInTheDocument();
    expect(within(s).getByText("Proyek Telat")).toBeInTheDocument();
    expect(within(s).getByText(/Ani SA/)).toBeInTheDocument();
    expect(within(s).getByText(/Belum ditugaskan/)).toBeInTheDocument();
    expect(within(s).getByRole("link", { name: "Proyek Telat" })).toHaveAttribute("href", "/projects/P9");
  });

  it("macet: project, status, lama dan ambang", async () => {
    isiSemua();
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    const s = section("Project Macet");
    expect(await within(s).findByRole("link", { name: "Proyek Macet" })).toHaveAttribute("href", "/projects/P5");
    expect(within(s).getByText("In Progress")).toBeInTheDocument();
    expect(within(s).getByText("18 hari (ambang 14 hari)")).toBeInTheDocument();
  });

  it("butuh aksi: label jenis dan tautan project", async () => {
    isiSemua();
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    const s = section("Butuh Aksi");
    expect(await within(s).findByRole("link", { name: "Proyek Antri" })).toHaveAttribute("href", "/projects/A1");
    expect(within(s).getByText("Menunggu assignment")).toBeInTheDocument();
    expect(within(s).getByText("DQ Number kosong")).toBeInTheDocument();
    expect(within(s).getByText("Need Clarification")).toBeInTheDocument();
    expect(within(s).getByRole("link", { name: "Proyek Klarifikasi" })).toHaveAttribute("href", "/projects/A3");
  });
});

const KASUS = [
  ["Beban SA", URL.beban, { minggu_mulai: "2030-01-07", items: [] }, "Belum ada SA terdaftar.", "Gagal memuat beban SA."],
  ["Due Date", URL.dueDate, { hari_peringatan: 3, subtask: [], project: [] }, "Tidak ada subtask atau project yang lewat atau mendekati due date.", "Gagal memuat data due date."],
  ["Project Macet", URL.macet, { ambang_hari: {}, items: [] }, "Tidak ada project yang terlalu lama di satu status.", "Gagal memuat project macet."],
  ["Butuh Aksi", URL.aksi, { items: [] }, "Tidak ada project yang butuh aksi.", "Gagal memuat project yang butuh aksi."],
] as const;

describe.each(KASUS)("Workload Lead_SA — %s: keadaan", (judul, path, kosong, pesanKosong, pesanGagal) => {
  it("memuat: skeleton", () => {
    isiSemua();
    hang(path);
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    expect(section(judul).querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("kosong: pesan kosong", async () => {
    isiSemua();
    ok(path, kosong);
    renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    expect(await within(section(judul)).findByText(pesanKosong)).toBeInTheDocument();
  });

  it("gagal: pesan error, bagian lain tetap tampil, dan coba lagi memuat ulang", async () => {
    isiSemua();
    fail(path);
    const { user } = renderWithProviders(<WorkloadPage />, { role: "Lead_SA" });
    expect(await within(section(judul)).findByText(pesanGagal)).toBeInTheDocument();
    ok(path, kosong);
    await user.click(within(section(judul)).getByRole("button", { name: "Coba lagi" }));
    expect(await within(section(judul)).findByText(pesanKosong)).toBeInTheDocument();
  });
});
