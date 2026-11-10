import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, setParams, successEnvelope, type Role } from "@/test";
import { makeStoryPage } from "@/test/fixtures/operations";
import ProjectActivityLogsPage from "./page";

function useProject() {
  server.use(
    http.get(api("/projects/:id"), () =>
      HttpResponse.json(successEnvelope({ id_project: "p-1", project_name: "Migrasi Cloud", customer_name: "PT Contoh" }))
    )
  );
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
    expect(screen.getByRole("link", { name: "+ Tambah Log" })).toHaveAttribute("href", "/activity-logs?project=p%201");
    await screen.findByText("Diskusi kebutuhan dengan customer");
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

  it.each<Role>(["SA", "Sales", "Lead_SA", "Admin"])("dapat dirender oleh peran %s", async (role) => {
    setParams({ id: "p-1" });
    useProject();
    renderWithProviders(<ProjectActivityLogsPage />, { role });
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
  });
});
