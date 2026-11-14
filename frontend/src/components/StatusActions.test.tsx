import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { users } from "@/test/fixtures/users";
import { makeSATambahan, makeTimSA } from "@/test/fixtures/project-detail";
import { useToastStore } from "@/store/toast";
import { StatusActions, type StatusActionsProject } from "./StatusActions";

const PID = "PRJ-1";

function proyek(status: string, extra: Partial<StatusActionsProject> = {}): StatusActionsProject {
  return {
    id_project: PID,
    status,
    previous_status: null,
    lost_reason: null,
    sales_pic: { id: users.Sales.id },
    product_pic: { id: users.Product.id },
    assigned_sa: { id: users.SA.id },
    ...extra,
  };
}

function setup(role: Role | undefined, project: StatusActionsProject) {
  const onChanged = vi.fn();
  const hasil = renderWithProviders(<StatusActions project={project} onChanged={onChanged} />, role ? { role } : {});
  return { ...hasil, onChanged };
}

/** Nama tombol di grup "Aksi status" (kosong bila grup tidak dirender). */
async function tombolAksi(): Promise<string[]> {
  // Beri kesempatan fetch tim-sa selesai sebelum menyimpulkan.
  await new Promise((r) => setTimeout(r, 30));
  const grup = screen.queryByRole("group", { name: "Aksi status" });
  return grup ? within(grup).getAllByRole("button").map((b) => b.textContent ?? "").sort() : [];
}

const SUBMITTED = "Tandai Submitted";
const REVISI = "Minta Revisi";
const WON = "Tandai Won";
const JEDA = "Jeda (On Hold)";
const LANJUT = "Lanjutkan";
const LOST = "Tandai Lost";
const CLOSED = "Tutup Proyek (Closed)";
const BUKA = "Buka Kembali";

beforeEach(() => {
  useToastStore.getState().clearAll();
});

type Baris = [status: string, previous: string | null, peran: Role, tampil: string[]];

// Matriks hak per peran dan status (spec §2.0; mencerminkan backend/app/api/workflow.py).
// Sales dan Product adalah PIC project fixture; SA adalah SA utama; Admin = SA dengan flag is_admin.
const MATRIKS: Baris[] = [
  ["Intake", null, "Lead_SA", [LOST]],
  ["Intake", null, "Admin", [LOST]],
  ["Intake", null, "Sales", []],
  ["Intake", null, "SA", []],
  ["Awaiting Assignment", null, "Sales", [JEDA]],
  ["Awaiting Assignment", null, "Product", [JEDA]],
  ["Awaiting Assignment", null, "SA", []],
  ["Awaiting Assignment", null, "Lead_SA", [JEDA, LOST]],
  ["Assigned", null, "SA", [SUBMITTED]],
  ["Assigned", null, "Sales", [JEDA]],
  ["Assigned", null, "Lead_SA", [SUBMITTED, JEDA, LOST]],
  ["Assigned", null, "Admin", [SUBMITTED, JEDA, LOST]],
  ["In Progress", null, "SA", [SUBMITTED]],
  ["In Progress", null, "Product", [JEDA]],
  ["In Progress", null, "Lead_SA", [SUBMITTED, JEDA, LOST]],
  ["Submitted", null, "SA", [REVISI]],
  ["Submitted", null, "Sales", [WON, JEDA]],
  ["Submitted", null, "Product", [WON, JEDA]],
  ["Submitted", null, "Lead_SA", [REVISI, WON, JEDA, LOST]],
  ["Submitted", null, "Admin", [REVISI, WON, JEDA, LOST]],
  ["Won", null, "Lead_SA", [LOST]],
  ["Won", null, "Sales", []],
  ["Won", null, "SA", []],
  ["Handed Over", null, "Lead_SA", [CLOSED]],
  ["Handed Over", null, "Admin", [CLOSED]],
  ["Handed Over", null, "Sales", []],
  ["Handed Over", null, "SA", []],
  ["On Hold", "In Progress", "Sales", [LANJUT]],
  ["On Hold", "In Progress", "Product", [LANJUT]],
  ["On Hold", "In Progress", "SA", []],
  ["On Hold", "In Progress", "Lead_SA", [LANJUT, LOST]],
  ["Closed", "Handed Over", "Admin", [BUKA]],
  ["Closed", "Handed Over", "Lead_SA", []],
  ["Closed", "Handed Over", "Sales", []],
  ["Lost", "Won", "Admin", [BUKA]],
  ["Lost", "Won", "Lead_SA", []],
  ["Lost", "Won", "SA", []],
];

describe("StatusActions — tombol per peran dan status", () => {
  it.each(MATRIKS)("%s (sebelumnya %s), peran %s → %j", async (status, previous, peran, tampil) => {
    setup(peran, proyek(status, { previous_status: previous }));
    expect(await tombolAksi()).toEqual([...tampil].sort());
  });

  it("tanpa pengguna login: tidak ada tombol", async () => {
    setup(undefined, proyek("Submitted"));
    expect(await tombolAksi()).toEqual([]);
  });

  it("Sales yang bukan PIC project tidak mendapat Won/Jeda", async () => {
    setup("Sales", proyek("Submitted", { sales_pic: { id: "lain" }, product_pic: { id: "lain-2" } }));
    expect(await tombolAksi()).toEqual([]);
  });

  it("SA yang bukan SA project tidak mendapat Submitted", async () => {
    setup("SA", proyek("Assigned", { assigned_sa: { id: "sa-lain" } }));
    expect(await tombolAksi()).toEqual([]);
  });

  it("SA tambahan (dari /tim-sa) mendapat Submitted", async () => {
    server.use(
      http.get(api("/projects/:id/tim-sa"), () =>
        HttpResponse.json(
          successEnvelope(
            makeTimSA({
              sa_utama: { id: "sa-lain", name: "Utama", email: "u@example.com" },
              sa_tambahan: [makeSATambahan({ id: users.SA.id })],
            }),
          ),
        ),
      ),
    );
    setup("SA", proyek("Assigned", { assigned_sa: { id: "sa-lain" } }));
    await waitFor(async () => expect(await tombolAksi()).toEqual([SUBMITTED]));
  });

  it("gagal memuat /tim-sa: SA utama dari detail proyek tetap dihitung", async () => {
    server.use(http.get(api("/projects/:id/tim-sa"), () => HttpResponse.json(errorEnvelope("gagal"), { status: 500 })));
    setup("SA", proyek("Assigned"));
    expect(await tombolAksi()).toEqual([SUBMITTED]);
  });
});

describe("StatusActions — catatan status", () => {
  it("Lost menampilkan alasan dan penanda read-only", async () => {
    setup("Sales", proyek("Lost", { previous_status: "Submitted", lost_reason: "Customer batal" }));
    expect(await screen.findByText(/Customer batal/)).toHaveTextContent("Alasan Lost: Customer batal");
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  });

  it("Closed menampilkan penanda read-only", async () => {
    setup("Sales", proyek("Closed", { previous_status: "Handed Over" }));
    expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
  });

  it("On Hold menampilkan status sebelumnya dan timer SLA berhenti", async () => {
    setup("Sales", proyek("On Hold", { previous_status: "Assigned" }));
    const catatan = await screen.findByText(/Timer SLA DQ berhenti/);
    expect(catatan).toHaveTextContent("Assigned");
  });

  it("status aktif tanpa aksi untuk peran itu: tidak merender apa pun", async () => {
    const { container } = setup("SA", proyek("Won"));
    await tombolAksi();
    expect(container).toBeEmptyDOMElement();
  });
});

/** Tangkap body PATCH /projects/{id}/status dan balas sukses. */
function tangkapPatch() {
  const diterima: { body?: unknown; url?: string } = {};
  server.use(
    http.patch(api("/projects/:id/status"), async ({ request, params }) => {
      diterima.body = await request.json();
      diterima.url = String(params.id);
      return HttpResponse.json(successEnvelope({ id_project: PID, old_status: "x", new_status: "y" }));
    }),
  );
  return diterima;
}

async function klikAksi(user: ReturnType<typeof setup>["user"], nama: string) {
  await screen.findByRole("group", { name: "Aksi status" });
  await user.click(screen.getByRole("button", { name: nama }));
  return screen.getByRole("dialog", { name: nama });
}

describe("StatusActions — dialog dan PATCH /projects/{id}/status", () => {
  it("Submitted: konfirmasi mengirim new_status tanpa reason, menutup dialog, memanggil onChanged, toast sukses", async () => {
    const diterima = tangkapPatch();
    const { user, onChanged } = setup("SA", proyek("Assigned"));
    const dialog = await klikAksi(user, SUBMITTED);
    expect(within(dialog).getByLabelText("Alasan (opsional)")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(diterima).toEqual({ url: PID, body: { new_status: "Submitted" } });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(useToastStore.getState().toasts).toEqual([expect.objectContaining({ type: "success" })]);
  });

  it("Batal menutup dialog tanpa request", async () => {
    const diterima = tangkapPatch();
    const { user, onChanged } = setup("Lead_SA", proyek("Submitted"));
    const dialog = await klikAksi(user, WON);
    await user.click(within(dialog).getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(diterima.body).toBeUndefined();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("Won oleh Sales PIC mengirim new_status Won", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("Sales", proyek("Submitted"));
    const dialog = await klikAksi(user, WON);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await waitFor(() => expect(diterima.body).toEqual({ new_status: "Won" }));
  });

  it("Revisi mengirim new_status In Progress", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("SA", proyek("Submitted"));
    const dialog = await klikAksi(user, REVISI);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await waitFor(() => expect(diterima.body).toEqual({ new_status: "In Progress" }));
  });

  it("Lost: alasan wajib; Konfirmasi nonaktif sampai alasan terisi, lalu mengirim lost reason (trim)", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("Lead_SA", proyek("Submitted"));
    const dialog = await klikAksi(user, LOST);
    const konfirmasi = within(dialog).getByRole("button", { name: "Konfirmasi" });
    expect(within(dialog).getByLabelText("Alasan (wajib)")).toBeInTheDocument();
    expect(konfirmasi).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Alasan (wajib)"), "   ");
    expect(konfirmasi).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Alasan (wajib)"), "  Customer memilih vendor lain ");
    expect(konfirmasi).toBeEnabled();
    await user.click(konfirmasi);

    await waitFor(() => expect(diterima.body).toEqual({ new_status: "Lost", reason: "Customer memilih vendor lain" }));
  });

  it("Jeda: alasan opsional dikirim bila diisi", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("Sales", proyek("Assigned"));
    const dialog = await klikAksi(user, JEDA);
    await user.type(within(dialog).getByLabelText("Alasan (opsional)"), "Menunggu PO");
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await waitFor(() => expect(diterima.body).toEqual({ new_status: "On Hold", reason: "Menunggu PO" }));
  });

  it("Lanjutkan mengirim new_status = previous_status", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("Product", proyek("On Hold", { previous_status: "In Progress" }));
    const dialog = await klikAksi(user, LANJUT);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await waitFor(() => expect(diterima.body).toEqual({ new_status: "In Progress" }));
  });

  it("Closed dari Handed Over mengirim new_status Closed", async () => {
    const diterima = tangkapPatch();
    const { user } = setup("Lead_SA", proyek("Handed Over"));
    const dialog = await klikAksi(user, CLOSED);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await waitFor(() => expect(diterima.body).toEqual({ new_status: "Closed" }));
  });

  it.each([
    ["Closed", "Handed Over"],
    ["Lost", "Submitted"],
  ])("Buka kembali %s oleh admin: alasan wajib, new_status = previous_status", async (status, previous) => {
    const diterima = tangkapPatch();
    const { user } = setup("Admin", proyek(status, { previous_status: previous, lost_reason: status === "Lost" ? "x" : null }));
    const dialog = await klikAksi(user, BUKA);
    const konfirmasi = within(dialog).getByRole("button", { name: "Konfirmasi" });
    expect(konfirmasi).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Alasan (wajib)"), "Customer minta lanjut");
    await user.click(konfirmasi);
    await waitFor(() => expect(diterima.body).toEqual({ new_status: previous, reason: "Customer minta lanjut" }));
  });
});

describe("StatusActions — error dari backend", () => {
  it.each([
    [400, "Status 'Submitted' butuh dokumen PropTek, BOQ, dan Mandays masing-masing minimal berstatus 'Reviewed'."],
    [403, "Hanya Lead_SA atau Admin yang dapat menjalankan transisi status ini."],
    [409, "Proyek berstatus 'Closed' bersifat read-only."],
  ])("status %i: pesan `message` tampil di dialog, dialog tetap terbuka, tanpa onChanged", async (kode, pesan) => {
    server.use(http.patch(api("/projects/:id/status"), () => HttpResponse.json(errorEnvelope(pesan), { status: kode })));
    const { user, onChanged } = setup("SA", proyek("Assigned"));
    const dialog = await klikAksi(user, SUBMITTED);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(pesan);
    expect(screen.getByRole("dialog", { name: SUBMITTED })).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Konfirmasi" })).toBeEnabled();
  });

  it("pesan error dibersihkan saat dialog dibuka ulang", async () => {
    server.use(http.patch(api("/projects/:id/status"), () => HttpResponse.json(errorEnvelope("Gagal"), { status: 400 })));
    const { user } = setup("SA", proyek("Assigned"));
    const dialog = await klikAksi(user, SUBMITTED);
    await user.click(within(dialog).getByRole("button", { name: "Konfirmasi" }));
    await within(dialog).findByRole("alert");
    await user.click(within(dialog).getByRole("button", { name: "Batal" }));
    await user.click(screen.getByRole("button", { name: SUBMITTED }));
    expect(within(screen.getByRole("dialog")).queryByRole("alert")).not.toBeInTheDocument();
  });
});
