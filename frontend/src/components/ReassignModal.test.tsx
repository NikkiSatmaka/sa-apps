import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { makeAvailableSA } from "@/test/fixtures/operations";
import { ReassignModal } from "./ReassignModal";

function setup(props: { currentSAName?: string | null } = {}) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  const utils = renderWithProviders(
    <ReassignModal
      projectId="p-1"
      projectName="Migrasi Cloud"
      customerName="PT Contoh"
      currentSAName={props.currentSAName}
      onClose={onClose}
      onSuccess={onSuccess}
    />,
    { role: "Lead_SA" }
  );
  return { onClose, onSuccess, ...utils };
}

describe("ReassignModal", () => {
  it("menampilkan judul, proyek, dan SA saat ini bila ada", async () => {
    setup({ currentSAName: "SA Lama" });
    expect(screen.getByRole("heading", { name: "Reassign SA" })).toBeInTheDocument();
    expect(screen.getByText("Migrasi Cloud — PT Contoh")).toBeInTheDocument();
    expect(screen.getByText("SA Lama")).toBeInTheDocument();
    await screen.findByText("Budi Santoso");
  });

  it("tidak menampilkan baris SA saat ini bila tidak ada", async () => {
    setup({ currentSAName: null });
    expect(screen.queryByText(/SA saat ini/)).not.toBeInTheDocument();
    await screen.findByText("Budi Santoso");
  });

  it("menampilkan skeleton lalu daftar SA dengan label workload Rendah/Sedang/Tinggi dan avatar", async () => {
    server.use(
      http.get(api("/sa/available"), () =>
        HttpResponse.json(
          successEnvelope([
            makeAvailableSA({ id: "a", name: "Rendah Satu", active_project_count: 0 }),
            makeAvailableSA({ id: "b", name: "Sedang Dua", active_project_count: 3 }),
            makeAvailableSA({ id: "c", name: "Tinggi Tiga", active_project_count: 5, avatar_url: "http://localhost/c.png" }),
          ])
        )
      )
    );
    const { container } = setup();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(await screen.findByText("Rendah Satu")).toBeInTheDocument();
    expect(screen.getByText("Rendah")).toBeInTheDocument();
    expect(screen.getByText("Sedang")).toBeInTheDocument();
    expect(screen.getByText("Tinggi")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Tinggi Tiga" })).toBeInTheDocument();
  });

  it("menampilkan keadaan kosong bila tidak ada SA tersedia", async () => {
    server.use(http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope([]))));
    setup();
    expect(await screen.findByText("Tidak ada SA yang tersedia saat ini.")).toBeInTheDocument();
  });

  it("mengirim sa_id baru ke endpoint reassign lalu memanggil onSuccess", async () => {
    let body: unknown;
    server.use(
      http.post(api("/projects/:id/reassign"), async ({ request, params }) => {
        body = { ...(await request.json() as object), project: params.id };
        return HttpResponse.json(successEnvelope({ id_project: "p-1", assigned_sa: "sa-2", assigned_sa_name: "Eka", status: "x" }));
      })
    );
    const { user, onSuccess } = setup();
    expect(screen.getByRole("button", { name: "Konfirmasi Reassign" })).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: /Eka Putri/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Reassign" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ sa_id: "sa-2", project: "p-1" });
  });

  it("menampilkan status 'Mereassign...' selama request", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/projects/:id/reassign"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup();
    await user.click(await screen.findByRole("button", { name: /Budi Santoso/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Reassign" }));
    expect(await screen.findByRole("button", { name: /Mereassign/ })).toBeDisabled();
    release();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("menampilkan pesan error server (403) tanpa memanggil onSuccess", async () => {
    server.use(
      http.post(api("/projects/:id/reassign"), () => HttpResponse.json(errorEnvelope("Tidak berhak reassign"), { status: 403 }))
    );
    const { user, onSuccess } = setup();
    await user.click(await screen.findByRole("button", { name: /Budi Santoso/ }));
    await user.click(screen.getByRole("button", { name: "Konfirmasi Reassign" }));
    expect(await screen.findByText("Tidak berhak reassign")).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("tidak mengirim request bila tidak ada SA terpilih", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/projects/:id/reassign"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await screen.findByText("Budi Santoso");
    await user.click(screen.getByRole("button", { name: "Konfirmasi Reassign" }));
    expect(hit).not.toHaveBeenCalled();
  });

  it("menutup modal lewat tombol Tutup, Batal, dan backdrop", async () => {
    const { user, onClose } = setup();
    await screen.findByText("Budi Santoso");
    await user.click(screen.getByRole("button", { name: "Tutup modal" }));
    await user.click(screen.getByRole("button", { name: "Batal" }));
    await user.click(document.querySelector('[aria-hidden="true"]') as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
