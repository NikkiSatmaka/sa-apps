import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { HandoverConfigForm } from "./HandoverConfigForm";

function setup(props: Partial<React.ComponentProps<typeof HandoverConfigForm>> = {}) {
  const onSuccess = vi.fn();
  const onCancel = vi.fn();
  const utils = renderWithProviders(
    <HandoverConfigForm projectId="p-1" onSuccess={onSuccess} onCancel={onCancel} {...props} />,
    { role: "SA" }
  );
  return { onSuccess, onCancel, ...utils };
}

const pmo = () => screen.getByLabelText(/Email PMO Lead/);
const delivery = () => screen.getByLabelText(/Email Delivery Lead/);

describe("HandoverConfigForm", () => {
  it("mengisi awal dari email yang sudah tersimpan", () => {
    setup({ existingPmoEmail: "pmo@x.com", existingDeliveryEmail: "del@x.com" });
    expect(pmo()).toHaveValue("pmo@x.com");
    expect(delivery()).toHaveValue("del@x.com");
  });

  it("form kosong: validasi wajib diisi untuk kedua field, tanpa request", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/projects/:id/handover-config"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup();
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(screen.getByText("PMO Lead wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Delivery Lead wajib diisi")).toBeInTheDocument();
    expect(pmo()).toBeInvalid();
    expect(hit).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("alamat tanpa TLD (lolos validasi native, gagal regex aplikasi) ditolak dan error hilang saat field diubah", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/projects/:id/handover-config"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await user.type(pmo(), "pmo@host");
    await user.type(delivery(), "a@b.co");
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(screen.getByText("Format email PMO Lead tidak valid")).toBeInTheDocument();
    expect(pmo()).toBeInvalid();
    expect(hit).not.toHaveBeenCalled();

    await user.type(pmo(), "x");
    expect(screen.queryByText("Format email PMO Lead tidak valid")).not.toBeInTheDocument();
  });

  it("format email Delivery tidak valid ditolak dan error hilang saat diubah", async () => {
    const { user } = setup();
    await user.type(pmo(), "p@b.co");
    await user.type(delivery(), "del@host");
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(screen.getByText("Format email Delivery Lead tidak valid")).toBeInTheDocument();
    await user.type(delivery(), "x");
    expect(screen.queryByText("Format email Delivery Lead tidak valid")).not.toBeInTheDocument();
  });

  it("alamat yang jelas salah ditahan validasi native browser (type=email) sebelum validasi aplikasi", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/projects/:id/handover-config"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup();
    await user.type(pmo(), "bukan-email");
    await user.type(delivery(), "a@b.co");
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(pmo()).toBeInvalid(); // constraint validation native
    expect(hit).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("sukses: mengirim email (di-trim) ke endpoint handover-config lalu memanggil onSuccess", async () => {
    let body: unknown;
    server.use(
      http.post(api("/projects/:id/handover-config"), async ({ request, params }) => {
        body = { ...(await request.json() as object), id: params.id };
        return HttpResponse.json(successEnvelope({ message: "ok" }));
      })
    );
    const { user, onSuccess } = setup();
    await user.type(pmo(), "  pmo@x.com ");
    await user.type(delivery(), "del@x.com");
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ pmo_email: "pmo@x.com", delivery_email: "del@x.com", id: "p-1" });
  });

  it("menampilkan 'Menyimpan...' dan menonaktifkan input selama request", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/projects/:id/handover-config"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup({ existingPmoEmail: "p@x.com", existingDeliveryEmail: "d@x.com" });
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(await screen.findByRole("button", { name: /Menyimpan/ })).toBeDisabled();
    expect(pmo()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
    release();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("error server (pesan dari backend) ditampilkan sebagai alert umum", async () => {
    server.use(
      http.post(api("/projects/:id/handover-config"), () => HttpResponse.json(errorEnvelope("Email tidak diizinkan"), { status: 422 }))
    );
    const { user, onSuccess } = setup({ existingPmoEmail: "p@x.com", existingDeliveryEmail: "d@x.com" });
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(await screen.findByText("Email tidak diizinkan")).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("error server tanpa pesan memakai pesan fallback berisi status", async () => {
    server.use(http.post(api("/projects/:id/handover-config"), () => new HttpResponse("x", { status: 500 })));
    const { user } = setup({ existingPmoEmail: "p@x.com", existingDeliveryEmail: "d@x.com" });
    await user.click(screen.getByRole("button", { name: "Simpan Konfigurasi" }));
    expect(await screen.findByText("Gagal menyimpan konfigurasi handover (status 500)")).toBeInTheDocument();
  });

  it("tombol Batal hanya ada bila onCancel diberikan dan memanggilnya", async () => {
    const { user, onCancel } = setup();
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("tanpa onCancel tidak ada tombol Batal", () => {
    setup({ onCancel: undefined });
    expect(screen.queryByRole("button", { name: "Batal" })).not.toBeInTheDocument();
  });
});
