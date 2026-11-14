import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HttpResponse, api, errorEnvelope, http, pasangHubungan, renderWithProviders, server, setParams, successEnvelope, type Hubungan, type Role } from "@/test";
import { makeStoryPage } from "@/test/fixtures/operations";
import ProjectActivityLogsPage from "./page";

// Proyek + hubungan pengguna ke proyek (bawaan: SA utama, berhak menulis log).
function useProject(role: Role = "SA", hubungan: Hubungan = "sa_utama") {
  pasangHubungan(role, hubungan, { id_project: "p-1", project_name: "Migrasi Cloud", customer_name: "PT Contoh" });
}

describe("ProjectActivityLogsPage", () => {
  it("menampilkan nama proyek + customer dan riwayat log setelah dimuat", async () => {
    setParams({ id: "p-1" });
    useProject();
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(screen.getByRole("heading", { name: "Riwayat Activity Log" })).toBeInTheDocument();
    expect(await screen.findByText("Migrasi Cloud — PT Contoh")).toBeInTheDocument();
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
  });

  it("sebelum data proyek tiba, menampilkan id proyek sebagai pengganti", async () => {
    setParams({ id: "p-1" });
    useProject();
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(screen.getByText("p-1")).toBeInTheDocument();
    await screen.findByText("Migrasi Cloud — PT Contoh");
  });

  it("tautan kembali ke proyek dan tambah log (id di-encode)", async () => {
    setParams({ id: "p 1" });
    useProject();
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(screen.getByRole("link", { name: "← Kembali ke proyek" })).toHaveAttribute("href", "/projects/p 1");
    expect(await screen.findByRole("link", { name: "+ Tambah Log" })).toHaveAttribute("href", "/activity-logs?project=p%201");
    await screen.findByText("Diskusi kebutuhan dengan customer");
  });

  it("Sales (PIC) membaca riwayat tetapi tidak melihat tombol + Tambah Log", async () => {
    setParams({ id: "p-1" });
    useProject("Sales", "sales_pic");
    renderWithProviders(<ProjectActivityLogsPage />, { role: "Sales" });
    await screen.findByText("Diskusi kebutuhan dengan customer");
    expect(screen.queryByRole("link", { name: "+ Tambah Log" })).not.toBeInTheDocument();
  });

  it("meminta story proyek yang sesuai dengan param id", async () => {
    setParams({ id: "p-77" });
    useProject();
    let path = "";
    server.use(
      http.get(api("/projects/:id/story"), ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope(makeStoryPage([])));
      })
    );
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(await screen.findByText("Belum ada activity log untuk proyek ini.")).toBeInTheDocument();
    expect(path).toBe("/api/v1/projects/p-77/story");
  });

  it("error memuat proyek: header tetap memakai id, riwayat tetap tampil", async () => {
    setParams({ id: "p-1" });
    server.use(http.get(api("/projects/:id"), () => HttpResponse.json(errorEnvelope("tidak ada"), { status: 404 })));
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
    expect(screen.getByText("p-1")).toBeInTheDocument();
  });

  it("error memuat riwayat: pesan gagal memuat", async () => {
    setParams({ id: "p-1" });
    useProject();
    server.use(http.get(api("/projects/:id/story"), () => HttpResponse.json(errorEnvelope("Tidak berhak"), { status: 403 })));
    renderWithProviders(<ProjectActivityLogsPage />, { role: "SA" });
    expect(await screen.findByText("Gagal memuat data: Tidak berhak")).toBeInTheDocument();
  });

  it.each<Role>(["SA", "Sales", "Product", "Lead_SA", "Admin"])("dapat dirender oleh peran %s", async (role) => {
    setParams({ id: "p-1" });
    useProject(role, "tak_terkait");
    renderWithProviders(<ProjectActivityLogsPage />, { role });
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
  });
});

// "+ Tambah Log" = TingkatAkses.TULIS (#154): SA ditugaskan, contributor, Lead_SA, Admin.
describe("ProjectActivityLogsPage — hak tulis per hubungan", () => {
  const KASUS: { role: Role; hubungan: Hubungan; berhak: boolean }[] = [
    { role: "SA", hubungan: "sa_utama", berhak: true },
    { role: "SA", hubungan: "sa_tambahan", berhak: true },
    { role: "SA", hubungan: "contributor", berhak: true },
    { role: "Lead_SA", hubungan: "tak_terkait", berhak: true },
    { role: "Admin", hubungan: "tak_terkait", berhak: true },
    { role: "Sales", hubungan: "sales_pic", berhak: false },
    { role: "Product", hubungan: "product_pic", berhak: false },
    { role: "SA", hubungan: "viewer", berhak: false },
    { role: "SA", hubungan: "tak_terkait", berhak: false },
  ];

  it.each(KASUS)("$role sebagai $hubungan: + Tambah Log tampil=$berhak, riwayat tetap terbaca", async ({ role, hubungan, berhak }) => {
    setParams({ id: "p-1" });
    useProject(role, hubungan);
    renderWithProviders(<ProjectActivityLogsPage />, { role });
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
    if (berhak) {
      expect(await screen.findByRole("link", { name: "+ Tambah Log" })).toBeInTheDocument();
    } else {
      await new Promise((r) => setTimeout(r, 50));
      expect(screen.queryByRole("link", { name: "+ Tambah Log" })).not.toBeInTheDocument();
    }
  });
});
