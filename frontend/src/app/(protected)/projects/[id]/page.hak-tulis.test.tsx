import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  api, http, HttpResponse, pasangHubungan, renderWithProviders, server, setParams, successEnvelope,
  type Hubungan, type Role,
} from "@/test";
import { makeHandoverReadiness } from "@/test/fixtures/operations";
import { DETAIL_ID } from "@/test/fixtures/project-detail";
import ProjectDetailPage from "./page";

/**
 * Hak tulis di halaman detail (#154): kontrol tulis tampil hanya bila peran/hubungan pengguna
 * berhak menurut spec §2.0 (`lib/akses.ts`). Anak nyata (tidak di-stub); konten baca tetap tampil.
 */
beforeEach(() => {
  setParams({ id: DETAIL_ID });
});

async function muat() {
  await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
  // Beri waktu hubungan (tim SA) selesai dimuat sebelum menyimpulkan "tersembunyi".
  await new Promise((r) => setTimeout(r, 50));
}

const EDIT: { role: Role; hubungan: Hubungan; berhak: boolean }[] = [
  { role: "SA", hubungan: "sa_utama", berhak: true },
  { role: "SA", hubungan: "sa_tambahan", berhak: true },
  { role: "Sales", hubungan: "sales_pic", berhak: true },
  { role: "Product", hubungan: "product_pic", berhak: true },
  { role: "Sales", hubungan: "contributor", berhak: true },
  { role: "Lead_SA", hubungan: "tak_terkait", berhak: true },
  { role: "Admin", hubungan: "tak_terkait", berhak: true },
  { role: "SA", hubungan: "viewer", berhak: false },
  { role: "SA", hubungan: "tak_terkait", berhak: false },
  { role: "Sales", hubungan: "tak_terkait", berhak: false },
  { role: "Product", hubungan: "tak_terkait", berhak: false },
];

describe("Detail proyek — tombol Edit (TingkatAkses.UBAH_PROYEK)", () => {
  it.each(EDIT)("$role sebagai $hubungan: Edit tampil=$berhak, detail tetap terbaca", async ({ role, hubungan, berhak }) => {
    pasangHubungan(role, hubungan);
    renderWithProviders(<ProjectDetailPage />, { role });
    await muat();
    expect(screen.getByText("PT ACME")).toBeInTheDocument();
    const edit = screen.queryByRole("button", { name: "Edit" });
    if (berhak) expect(edit).toBeInTheDocument();
    else expect(edit).not.toBeInTheDocument();
  });
});

describe("Detail proyek — konfigurasi dan modal handover Won", () => {
  const BELUM_LENGKAP = { pmo_email: null, delivery_email: null };
  function serveHandover(dipanggil?: { n: number }) {
    server.use(
      http.get(api(`/projects/${DETAIL_ID}/handover-status`), () => {
        if (dipanggil) dipanggil.n += 1;
        return HttpResponse.json(successEnvelope(makeHandoverReadiness(BELUM_LENGKAP)));
      }),
    );
  }

  it("Lead_SA melihat form konfigurasi handover (hanya Lead_SA/Admin yang berhak mengubahnya)", async () => {
    serveHandover();
    pasangHubungan("Lead_SA", "tak_terkait", { status: "Won" });
    renderWithProviders(<ProjectDetailPage />, { role: "Lead_SA" });
    expect(await screen.findByText("Konfigurasi Handover")).toBeInTheDocument();
  });

  it("SA ditugaskan: tidak melihat form konfigurasi handover (backend menolak selain Lead_SA/Admin)", async () => {
    serveHandover();
    pasangHubungan("SA", "sa_utama", { status: "Won" });
    renderWithProviders(<ProjectDetailPage />, { role: "SA" });
    await muat();
    expect(screen.queryByText("Konfigurasi Handover")).not.toBeInTheDocument();
  });

  it.each<{ role: Role; hubungan: Hubungan }>([
    { role: "Sales", hubungan: "sales_pic" },
    { role: "Product", hubungan: "tak_terkait" },
    { role: "SA", hubungan: "tak_terkait" },
    { role: "SA", hubungan: "contributor" },
  ])("$role sebagai $hubungan: handover-status tidak diminta dan tanpa pesan galat handover", async ({ role, hubungan }) => {
    const dipanggil = { n: 0 };
    serveHandover(dipanggil);
    pasangHubungan(role, hubungan, { status: "Won" });
    renderWithProviders(<ProjectDetailPage />, { role });
    await muat();
    expect(dipanggil.n).toBe(0);
    expect(screen.queryByText("Gagal memuat status handover.")).not.toBeInTheDocument();
  });

  it("SA tak terkait tidak melihat modal pemberitahuan handover; SA ditugaskan melihat", async () => {
    serveHandover();
    pasangHubungan("SA", "tak_terkait", { status: "Won" });
    const { unmount } = renderWithProviders(<ProjectDetailPage />, { role: "SA" });
    await muat();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();

    pasangHubungan("SA", "sa_tambahan", { status: "Won" });
    renderWithProviders(<ProjectDetailPage />, { role: "SA" });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
