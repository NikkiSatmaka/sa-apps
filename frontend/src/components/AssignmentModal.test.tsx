import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { makeAvailableSA, makePendingProject } from "@/test/fixtures/operations";
import { AssignmentModal } from "./AssignmentModal";

function setup(project = makePendingProject()) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  const utils = renderWithProviders(<AssignmentModal project={project} onClose={onClose} onSuccess={onSuccess} />, {
    role: "Lead_SA",
  });
  return { onClose, onSuccess, project, ...utils };
}

describe("AssignmentModal", () => {
  it("menampilkan skeleton saat daftar SA dimuat, lalu daftar SA beserta workload", async () => {
    const { container } = setup();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Konfirmasi Assignment" })).toBeDisabled();

    expect(await screen.findByText("Budi Santoso")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
    expect(screen.getByText("Rendah")).toBeInTheDocument(); // 1 proyek
    expect(screen.getByText("Sedang")).toBeInTheDocument(); // 4 proyek
  });

  it("menampilkan info proyek, status BANT Passed, dan use case tag", async () => {
    setup(makePendingProject({ bant_score: 60, use_case_tags: ["Cloud Migration", "Security"] }));
    expect(screen.getByText("Migrasi Cloud — PT Contoh")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    await screen.findByText("Budi Santoso");
  });

  it("menampilkan Not Passed bila skor BANT < 60 dan tanpa tag", async () => {
    setup(makePendingProject({ bant_score: 59, use_case_tags: [] }));
    expect(screen.getByText("Not Passed")).toBeInTheDocument();
    await screen.findByText("Budi Santoso");
  });

  it("menandai workload Tinggi (5+) dan memakai avatar bila tersedia", async () => {
    server.use(
      http.get(api("/sa/available"), () =>
        HttpResponse.json(
          successEnvelope([
            makeAvailableSA({ id: "sa-9", name: "Sibuk Sekali", active_project_count: 6, avatar_url: "http://localhost/a.png" }),
          ])
        )
      )
    );
    setup();
    expect(await screen.findByText("Tinggi")).toBeInTheDocument();
    expect(screen.getByText("6 proyek")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Sibuk Sekali" })).toHaveAttribute("src", "http://localhost/a.png");
  });

  it("menampilkan keadaan kosong bila tidak ada SA tersedia", async () => {
    server.use(http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([]))));
    setup();
    expect(await screen.findByText("Tidak ada SA yang tersedia saat ini.")).toBeInTheDocument();
  });

  it("mengaktifkan tombol konfirmasi setelah SA dipilih, mengirim sa_id, lalu memanggil onSuccess", async () => {
    let body: unknown;
    let auth: string | null = null;
    server.use(
      http.post(api("/projects/:id/assign"), async ({ request, params }) => {
        body = await request.json();
        auth = request.headers.get("Authorization");
        expect(params.id).toBe("11111111-1111-4111-8111-111111111111");
        return HttpResponse.json(successEnvelope({ id_project: "x", assigned_sa: "sa-2", assigned_at: "", status: "Assigned" }));
      })
    );
    const { user, onSuccess, onClose } = setup();
    await user.click(await screen.findByRole("button", { name: /Eka Putri/ }));
    const confirm = screen.getByRole("button", { name: "Konfirmasi Assignment" });
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ sa_id: "sa-2" });
    expect(auth).toBe("Bearer access-Lead_SA");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("menampilkan status 'Mengassign...' dan menonaktifkan tombol saat request berjalan", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(
      http.post(api("/projects/:id/assign"), async () => {
        await gate;
        return HttpResponse.json(successEnvelope({}));
      })
    );
    const { user, onSuccess } = setup();
    await user.click(await screen.findByRole("button", { name: /Budi Santoso/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Assignment" }));

    expect(await screen.findByRole("button", { name: /Mengassign/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
    release();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("menampilkan pesan error server dan tidak memanggil onSuccess", async () => {
    server.use(
      http.post(api("/projects/:id/assign"), () =>
        HttpResponse.json(errorEnvelope("SA sudah penuh"), { status: 409 })
      )
    );
    const { user, onSuccess } = setup();
    await user.click(await screen.findByRole("button", { name: /Budi Santoso/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Assignment" }));

    expect(await screen.findByText("SA sudah penuh")).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
    // tombol kembali aktif untuk mencoba ulang
    expect(screen.getByRole("button", { name: "Konfirmasi Assignment" })).toBeEnabled();
  });

  it("memakai pesan fallback ketika error server tanpa pesan", async () => {
    server.use(http.post(api("/projects/:id/assign"), () => new HttpResponse("oops", { status: 500 })));
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: /Budi Santoso/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Assignment" }));
    expect(await screen.findByText("Request gagal dengan status 500")).toBeInTheDocument();
  });

  it("menutup modal lewat tombol Tutup, Batal, dan klik backdrop", async () => {
    const { user, onClose } = setup();
    await screen.findByText("Budi Santoso");
    await user.click(screen.getByRole("button", { name: "Tutup modal" }));
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    const backdrop = document.querySelector('[aria-hidden="true"]') as HTMLElement;
    await user.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("tidak memanggil API assign bila belum ada SA terpilih", async () => {
    const assign = vi.fn();
    server.use(http.post(api("/projects/:id/assign"), () => { assign(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await screen.findByText("Budi Santoso");
    await user.click(screen.getByRole("button", { name: "Konfirmasi Assignment" }));
    expect(assign).not.toHaveBeenCalled();
  });

  it("tidak menampilkan daftar SA maupun pesan error bila daftar SA gagal dimuat (perilaku nyata)", async () => {
    server.use(http.get(api("/sa/available"), () => HttpResponse.json(errorEnvelope("gagal"), { status: 500 })));
    const { container } = setup();
    await waitFor(() => expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0));
    expect(screen.queryByText("Tidak ada SA yang tersedia saat ini.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Konfirmasi Assignment" })).toBeDisabled();
  });
});
