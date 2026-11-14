import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { users } from "@/test/fixtures/users";
import { makeSATambahan, makeTimSA } from "@/test/fixtures/project-detail";
import { useToastStore } from "@/store/toast";
import { HandoverAction, type HandoverActionProject } from "./HandoverAction";

const PID = "PRJ-1";

function proyek(status = "Won", extra: Partial<HandoverActionProject> = {}): HandoverActionProject {
  return { id_project: PID, project_name: "Migrasi Cloud ACME", status, assigned_sa: { id: users.SA.id }, ...extra };
}

/** Bentuk sama dengan `HandoverReadiness` backend (schemas/handover.py). */
function kesiapan(extra: Record<string, unknown> = {}) {
  return {
    ready: true,
    missing_items: [],
    pmo_email: "pmo@example.com",
    delivery_email: "delivery@example.com",
    project_status: "Won",
    hld_status: "Final",
    ...extra,
  };
}

function serveKesiapan(data: Record<string, unknown>) {
  server.use(http.get(api(`/projects/${PID}/handover-status`), () => HttpResponse.json(successEnvelope(data))));
}

function setup(role: Role | undefined, project: HandoverActionProject = proyek()) {
  const onDone = vi.fn();
  const hasil = renderWithProviders(<HandoverAction project={project} onDone={onDone} />, role ? { role } : {});
  return { ...hasil, onDone };
}

async function tungguTim() {
  // Beri kesempatan fetch tim-sa selesai sebelum menyimpulkan tombol tidak ada.
  await new Promise((r) => setTimeout(r, 30));
}

beforeEach(() => {
  useToastStore.getState().clearAll();
  serveKesiapan(kesiapan());
});

describe("HandoverAction — tombol per peran dan status", () => {
  it.each(["SA", "Lead_SA", "Admin"] as const)("%s melihat tombol Handover pada Won", async (role) => {
    setup(role);
    expect(await screen.findByRole("button", { name: "Handover" })).toBeInTheDocument();
  });

  it.each(["Sales", "Product"] as const)("%s tidak melihat tombol Handover pada Won", async (role) => {
    setup(role);
    await tungguTim();
    expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument();
  });

  it("tanpa aktor tidak ada tombol", async () => {
    setup(undefined);
    await tungguTim();
    expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument();
  });

  it("SA yang bukan SA ditugaskan tidak melihat tombol", async () => {
    setup("SA", proyek("Won", { assigned_sa: { id: "sa-lain" } }));
    await tungguTim();
    expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument();
  });

  it("SA tambahan (tim-sa) melihat tombol", async () => {
    server.use(
      http.get(api(`/projects/${PID}/tim-sa`), () =>
        HttpResponse.json(successEnvelope(makeTimSA({ sa_utama: { id: "sa-lain", name: "X", email: "x@x" }, sa_tambahan: [makeSATambahan({ id: users.SA.id })] }))),
      ),
    );
    setup("SA", proyek("Won", { assigned_sa: { id: "sa-lain" } }));
    expect(await screen.findByRole("button", { name: "Handover" })).toBeInTheDocument();
  });

  it.each(["Intake", "Awaiting Assignment", "Assigned", "In Progress", "Submitted", "Handed Over", "Closed", "Lost", "On Hold"])(
    "tidak tampil pada status %s",
    async (status) => {
      setup("Lead_SA", proyek(status));
      await tungguTim();
      expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument();
    },
  );
});

describe("HandoverAction — dialog kesiapan dan submit", () => {
  it("siap: dialog menampilkan email PMO/Delivery dan submit memanggil POST /handover lalu onDone", async () => {
    let dipanggil = 0;
    server.use(
      http.post(api(`/projects/${PID}/handover`), () => {
        dipanggil += 1;
        return HttpResponse.json(
          successEnvelope({
            id_project: PID, project_name: "Migrasi Cloud ACME", customer_name: "ACME", old_status: "Won", new_status: "Handed Over",
            pmo_email: "pmo@example.com", delivery_email: "delivery@example.com", final_deliverables_folder_id: "f1",
            documents_handed_over: ["HLD"], handover_at: "2025-01-05T00:00:00Z",
          }),
        );
      }),
    );
    const { user, onDone } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    expect(await within(dialog).findByText("pmo@example.com")).toBeInTheDocument();
    expect(within(dialog).getByText("delivery@example.com")).toBeInTheDocument();
    const kirim = within(dialog).getByRole("button", { name: "Konfirmasi Handover" });
    await waitFor(() => expect(kirim).toBeEnabled());
    await user.click(kirim);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(dipanggil).toBe(1);
    expect(screen.queryByRole("dialog", { name: "Handover Proyek" })).not.toBeInTheDocument();
    expect(useToastStore.getState().toasts.some((t) => t.type === "success")).toBe(true);
  });

  it("belum siap: missing_items ditampilkan dan submit ditahan (tidak ada POST)", async () => {
    serveKesiapan(kesiapan({ ready: false, missing_items: ["HLD berstatus Final", "Email Delivery Lead belum dikonfigurasi"], delivery_email: null, hld_status: "Draft" }));
    let dipanggil = 0;
    server.use(http.post(api(`/projects/${PID}/handover`), () => { dipanggil += 1; return HttpResponse.json(successEnvelope({})); }));
    const { user, onDone } = setup("SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    expect(await within(dialog).findByText("HLD berstatus Final")).toBeInTheDocument();
    expect(within(dialog).getByText("Email Delivery Lead belum dikonfigurasi")).toBeInTheDocument();
    const kirim = within(dialog).getByRole("button", { name: "Konfirmasi Handover" });
    expect(kirim).toBeDisabled();
    await user.click(kirim);
    expect(dipanggil).toBe(0);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("selama kesiapan belum dimuat submit dinonaktifkan", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api(`/projects/${PID}/handover-status`), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(kesiapan()));
      }),
    );
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    expect(within(dialog).getByRole("button", { name: "Konfirmasi Handover" })).toBeDisabled();
    lepas();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Konfirmasi Handover" })).toBeEnabled());
  });

  it("kesiapan gagal dimuat: pesan error tampil dan submit tetap ditahan", async () => {
    server.use(http.get(api(`/projects/${PID}/handover-status`), () => HttpResponse.json(errorEnvelope("Proyek tidak ditemukan"), { status: 404 })));
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Gagal memuat kesiapan handover");
    expect(within(dialog).getByRole("button", { name: "Konfirmasi Handover" })).toBeDisabled();
  });

  it.each([
    [400, "HLD belum Final"],
    [403, "Anda hanya dapat memicu handover proyek yang ditugaskan kepada Anda."],
    [409, "Status proyek sudah berubah"],
  ])("error %i dari backend tampil di dialog, dialog tetap terbuka, onDone tidak dipanggil", async (status, pesan) => {
    server.use(http.post(api(`/projects/${PID}/handover`), () => HttpResponse.json(errorEnvelope(pesan), { status })));
    const { user, onDone } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    const kirim = within(dialog).getByRole("button", { name: "Konfirmasi Handover" });
    await waitFor(() => expect(kirim).toBeEnabled());
    await user.click(kirim);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(pesan);
    expect(screen.getByRole("dialog", { name: "Handover Proyek" })).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
    expect(kirim).toBeEnabled();
  });

  it("selama mengirim tombol berubah 'Memproses...' dan dinonaktifkan; Batal menutup dialog", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.post(api(`/projects/${PID}/handover`), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope({ new_status: "Handed Over" }));
      }),
    );
    const { user, onDone } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Konfirmasi Handover" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi Handover" }));
    expect(await within(dialog).findByRole("button", { name: "Memproses..." })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Batal" })).toBeDisabled();
    lepas();
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("Batal menutup dialog tanpa memanggil POST", async () => {
    const { user, onDone } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    await user.click(within(dialog).getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("dialog", { name: "Handover Proyek" })).not.toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });
});
