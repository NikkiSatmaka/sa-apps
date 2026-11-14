import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, router, selaluGagal, server, successEnvelope } from "@/test";
import { makeTugasSaya } from "@/test/fixtures/project-detail";
import { TugasSayaSection } from "./TugasSayaSection";

function serve(items = [makeTugasSaya()], dicatat?: URLSearchParams[]) {
  server.use(
    http.get(api("/subtasks/saya"), ({ request }) => {
      dicatat?.push(new URL(request.url).searchParams);
      return HttpResponse.json(successEnvelope({ items, total: items.length }));
    }),
  );
}

describe("TugasSayaSection", () => {
  it("memuat: skeleton tanpa pesan kosong", () => {
    server.use(http.get(api("/subtasks/saya"), () => new Promise(() => {})));
    const { container } = renderWithProviders(<TugasSayaSection />, { role: "SA" });
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(screen.queryByText("Belum ada tugas yang ditugaskan kepada Anda.")).not.toBeInTheDocument();
  });

  it("menampilkan project, status, due date, estimasi, dan penanda terlambat", async () => {
    serve([
      makeTugasSaya({
        id_subtask: "a",
        title: "Rancang arsitektur",
        status: "in_progress",
        due_date: "2026-03-05",
        estimate_hours: "6.50",
        terlambat: true,
        id_project: "PRJ-1",
      }),
      makeTugasSaya({ id_subtask: "b", title: "Tinjau dokumen", status: "done", project_name: "Proyek Beta", customer_name: "PT Beta" }),
    ]);
    renderWithProviders(<TugasSayaSection />, { role: "SA" });

    const baris = await screen.findByRole("listitem", { name: "Tugas Rancang arsitektur" });
    expect(within(baris).getByText("Dikerjakan")).toBeInTheDocument();
    expect(within(baris).getByText(/5 Mar 2026/)).toBeInTheDocument();
    expect(within(baris).getByText(/6,5 jam/)).toBeInTheDocument();
    expect(within(baris).getByText("Terlambat")).toBeInTheDocument();
    expect(within(baris).getByRole("link", { name: /Proyek Alfa/ })).toHaveAttribute("href", "/projects/PRJ-1");
    expect(within(baris).getByText("PT Alfa")).toBeInTheDocument();

    const lain = screen.getByRole("listitem", { name: "Tugas Tinjau dokumen" });
    expect(within(lain).getByText("Selesai")).toBeInTheDocument();
    expect(within(lain).queryByText("Terlambat")).not.toBeInTheDocument();
    expect(within(lain).getByText("Proyek Beta", { exact: false })).toBeInTheDocument();
  });

  it("kosong: pesan belum ada tugas", async () => {
    serve([]);
    renderWithProviders(<TugasSayaSection />, { role: "SA" });
    expect(await screen.findByText("Belum ada tugas yang ditugaskan kepada Anda.")).toBeInTheDocument();
  });

  it("gagal memuat: pesan error, lalu 'Coba lagi' memulihkan daftar", async () => {
    server.use(gagalLaluBerhasil("/subtasks/saya", { items: [makeTugasSaya({ title: "Pulih" })], total: 1 }));
    const { user } = renderWithProviders(<TugasSayaSection />, { role: "SA" });
    expect(await screen.findByText("Gagal memuat tugas Anda.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByText("Pulih")).toBeInTheDocument();
  });

  it("gagal terus: error tampil, bukan keadaan kosong", async () => {
    server.use(selaluGagal("/subtasks/saya"));
    renderWithProviders(<TugasSayaSection />, { role: "SA" });
    expect(await screen.findByText("Gagal memuat tugas Anda.")).toBeInTheDocument();
    expect(screen.queryByText("Belum ada tugas yang ditugaskan kepada Anda.")).not.toBeInTheDocument();
  });

  it("awalnya tanpa filter: semua status dan tanpa project selesai", async () => {
    const dicatat: URLSearchParams[] = [];
    serve([makeTugasSaya()], dicatat);
    renderWithProviders(<TugasSayaSection />, { role: "SA" });
    await screen.findByText("Peer Review HLD");
    expect(dicatat).toHaveLength(1);
    expect(dicatat[0].getAll("status")).toEqual([]);
    expect(dicatat[0].get("sertakan_project_selesai")).toBeNull();
  });

  it("checkbox project selesai memakai ukuran 18px dan label target 44px", async () => {
    serve();
    renderWithProviders(<TugasSayaSection />, { role: "SA" });
    const checkbox = await screen.findByRole("checkbox", { name: "Sertakan project Closed/Lost" });

    expect(checkbox).toHaveClass("h-[18px]", "w-[18px]", "min-h-[18px]", "min-w-[18px]");
    expect(checkbox.closest("label")).toHaveClass("min-h-[44px]");
  });

  it("filter status mengirim ?status= lalu memuat ulang daftar", async () => {
    const dicatat: URLSearchParams[] = [];
    server.use(
      http.get(api("/subtasks/saya"), ({ request }) => {
        const params = new URL(request.url).searchParams;
        dicatat.push(params);
        const hanyaOpen = params.get("status") === "open";
        const items = hanyaOpen ? [makeTugasSaya({ title: "Hanya terbuka" })] : [makeTugasSaya({ title: "Semua" })];
        return HttpResponse.json(successEnvelope({ items, total: items.length }));
      }),
    );
    const { user } = renderWithProviders(<TugasSayaSection />, { role: "SA" });
    await screen.findByText("Semua");

    await user.selectOptions(screen.getByLabelText("Status"), "open");

    expect(await screen.findByText("Hanya terbuka")).toBeInTheDocument();
    expect(dicatat.at(-1)?.getAll("status")).toEqual(["open"]);
  });

  it("opsi 'Sertakan project Closed/Lost' mengirim sertakan_project_selesai=true", async () => {
    const dicatat: URLSearchParams[] = [];
    serve([makeTugasSaya()], dicatat);
    const { user } = renderWithProviders(<TugasSayaSection />, { role: "SA" });
    await screen.findByText("Peer Review HLD");

    await user.click(screen.getByRole("checkbox", { name: "Sertakan project Closed/Lost" }));

    await waitFor(() => expect(dicatat.at(-1)?.get("sertakan_project_selesai")).toBe("true"));
  });

  it("tautan project mengarah ke halaman detail project", async () => {
    serve([makeTugasSaya({ id_project: "PRJ-9", project_name: "Sembilan" })]);
    renderWithProviders(<TugasSayaSection />, { role: "SA" });
    expect(await screen.findByRole("link", { name: /Sembilan/ })).toHaveAttribute("href", "/projects/PRJ-9");
    expect(router.push).not.toHaveBeenCalled();
  });
});
