import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HttpResponse, api, gagalLaluBerhasil, http, renderWithProviders, server, setSearchParams, successEnvelope, type Role } from "@/test";
import { makeProject } from "@/test/fixtures/projects";
import ActivityLogsPage from "./page";

function useProjects() {
  server.use(
    http.get(api("/projects"), () =>
      HttpResponse.json(
        successEnvelope([
          makeProject({ id_project: "p-1", project_name: "Migrasi Cloud", status: "New" }),
          makeProject({ id_project: "p-2", project_name: "Rollout Jaringan", status: "Handover Complete" }),
        ])
      )
    )
  );
}

describe("ActivityLogsPage", () => {
  it("menampilkan skeleton saat proyek dimuat, lalu form dengan daftar proyek", async () => {
    useProjects();
    const { container } = renderWithProviders(<ActivityLogsPage />, { role: "SA" });
    expect(screen.getByRole("heading", { name: "Activity Log" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(screen.queryByRole("form", { name: "Form activity log" })).not.toBeInTheDocument();

    expect(await screen.findByRole("form", { name: "Form activity log" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
    expect(screen.getByRole("option", { name: "Migrasi Cloud" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Rollout Jaringan" })).toBeInTheDocument();
  });

  it("memiliki tautan ke Calendar Sync dan tanpa tautan riwayat bila tidak ada ?project", async () => {
    useProjects();
    renderWithProviders(<ActivityLogsPage />, { role: "SA" });
    await screen.findByRole("form", { name: "Form activity log" });
    expect(screen.getByRole("link", { name: "Calendar Sync" })).toHaveAttribute("href", "/activity-logs/calendar");
    expect(screen.queryByRole("link", { name: "Riwayat Log Proyek" })).not.toBeInTheDocument();
  });

  it("?project=<id> memilih proyek otomatis (fase dari status) dan menampilkan tautan riwayat", async () => {
    useProjects();
    setSearchParams("project=p-2");
    renderWithProviders(<ActivityLogsPage />, { role: "SA" });
    await screen.findByRole("form", { name: "Form activity log" });
    expect(screen.getByLabelText(/^Proyek/)).toHaveValue("p-2");
    expect(screen.getByLabelText(/^Fase Proyek/)).toHaveValue("Implementation");
    expect(screen.getByRole("link", { name: "Riwayat Log Proyek" })).toHaveAttribute("href", "/projects/p-2/activity-logs");
  });

  it("daftar proyek kosong: form tetap tampil tanpa pilihan proyek", async () => {
    server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope([]))));
    renderWithProviders(<ActivityLogsPage />, { role: "SA" });
    await screen.findByRole("form", { name: "Form activity log" });
    expect(screen.getAllByRole("option", { name: "Pilih proyek..." })).toHaveLength(1);
    expect(screen.queryByRole("option", { name: "Migrasi Cloud" })).not.toBeInTheDocument();
  });

  it("error memuat proyek: pesan error menggantikan form (daftar proyek kosong tak berguna), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/projects", [makeProject({ id_project: "p-1", project_name: "Migrasi Cloud", status: "New" })]));
    const { user } = renderWithProviders(<ActivityLogsPage />, { role: "SA" });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar proyek.");
    expect(screen.queryByRole("form", { name: "Form activity log" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByRole("form", { name: "Form activity log" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Migrasi Cloud" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each<Role>(["SA", "Sales", "Lead_SA", "Admin"])("halaman dapat diakses peran %s (tanpa pembatasan peran)", async (role) => {
    useProjects();
    renderWithProviders(<ActivityLogsPage />, { role });
    expect(await screen.findByRole("form", { name: "Form activity log" })).toBeInTheDocument();
  });

  it("mengirim activity log dari halaman dan form ter-reset setelah sukses", async () => {
    useProjects();
    let body: unknown;
    server.use(http.post(api("/activity-logs"), async ({ request }) => { body = await request.json(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = renderWithProviders(<ActivityLogsPage />, { role: "SA" });
    await screen.findByRole("form", { name: "Form activity log" });
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Assessment");
    await user.type(screen.getByLabelText(/^Catatan/), "Catatan hari ini");
    await user.click(screen.getByRole("button", { name: "Simpan Activity Log" }));
    await screen.findByText("Activity log berhasil disimpan");
    expect(body).toMatchObject({ id_project: "p-1", raw_notes: "Catatan hari ini", work_type: "Project" });
    await waitFor(() => expect(screen.getByLabelText(/^Catatan/)).toHaveValue(""));
  });
});
