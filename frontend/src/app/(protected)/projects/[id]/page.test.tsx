import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, errorEnvelope, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, router, server, setParams, stubLocation,
  successEnvelope, type Role,
} from "@/test";
import { makeHandoverReadiness } from "@/test/fixtures/operations";
import { DETAIL_ID, makeProjectDetail, makeSourceDoc, makeStoryItem } from "@/test/fixtures/project-detail";
import ProjectDetailPage from "./page";

// Anak milik tiket lain (F4/F6/F7) di-stub: yang diuji di sini hanya wiring halaman detail.
vi.mock("@/components/HandoverModal", () => ({
  HandoverModal: ({ projectName, onAcknowledge }: { projectName: string; onAcknowledge: () => void }) => (
    <div role="dialog" aria-label="stub handover">
      Handover {projectName}
      <button onClick={onAcknowledge}>Ack handover</button>
    </div>
  ),
}));
vi.mock("@/components/HandoverConfigForm", () => ({
  HandoverConfigForm: ({ existingPmoEmail, existingDeliveryEmail }: { existingPmoEmail?: string | null; existingDeliveryEmail?: string | null }) => (
    <div>Stub config form pmo={existingPmoEmail ?? "-"} delivery={existingDeliveryEmail ?? "-"}</div>
  ),
}));
vi.mock("@/components/AssignmentModal", () => ({
  AssignmentModal: ({ project, onClose, onSuccess }: { project: { project_name: string; bant_score: number; target_submit: string }; onClose: () => void; onSuccess: () => void }) => (
    <div role="dialog" aria-label="stub assign">
      Assign {project.project_name} bant={project.bant_score} target={project.target_submit}
      <button onClick={onClose}>Tutup assign</button>
      <button onClick={onSuccess}>Sukses assign</button>
    </div>
  ),
}));
vi.mock("@/components/ReassignModal", () => ({
  ReassignModal: ({ currentSAName, onClose, onSuccess }: { currentSAName?: string | null; onClose: () => void; onSuccess: () => void }) => (
    <div role="dialog" aria-label="stub reassign">
      Reassign dari {currentSAName}
      <button onClick={onClose}>Tutup reassign</button>
      <button onClick={onSuccess}>Sukses reassign</button>
    </div>
  ),
}));
vi.mock("@/components/CollaboratorSection", () => ({
  CollaboratorSection: ({ initialCollaborators }: { initialCollaborators: unknown[] }) => (
    <div>Stub kolaborator: {initialCollaborators.length}</div>
  ),
}));
vi.mock("@/components/PeopleSection", () => ({
  PeopleSection: ({ project }: { project: { id_project: string } }) => <div>Stub orang: {project.id_project}</div>,
}));
vi.mock("@/components/QualificationSection", () => ({
  QualificationSection: () => <div>Stub kualifikasi</div>,
}));

function serveDetail(overrides: Record<string, unknown> = {}) {
  server.use(http.get(api("/projects/:id"), () => HttpResponse.json(successEnvelope(makeProjectDetail(overrides)))));
}

function setup(role: Role | undefined, overrides: Record<string, unknown> = {}) {
  serveDetail(overrides);
  return renderWithProviders(<ProjectDetailPage />, role ? { role } : {});
}

beforeEach(() => {
  setParams({ id: DETAIL_ID });
});

describe("Detail proyek — memuat dan error", () => {
  it("menampilkan skeleton saat memuat lalu konten", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api("/projects/:id"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(makeProjectDetail()));
      }),
    );
    const { container } = renderWithProviders(<ProjectDetailPage />, { role: "Lead_SA" });
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    lepas();
    expect(await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" })).toBeInTheDocument();
  });

  it("error server menampilkan pesan gagal memuat tanpa konten", async () => {
    server.use(http.get(api("/projects/:id"), () => HttpResponse.json(errorEnvelope("Not found"), { status: 404 })));
    renderWithProviders(<ProjectDetailPage />, { role: "Lead_SA" });
    expect(await screen.findByText("Gagal memuat detail proyek. Silakan coba lagi.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("memanggil API dengan id dari URL", async () => {
    setParams({ id: "abc-123" });
    let id = "";
    server.use(
      http.get(api("/projects/:id"), ({ params }) => {
        id = String(params.id);
        return HttpResponse.json(successEnvelope(makeProjectDetail({ id_project: "abc-123" })));
      }),
    );
    renderWithProviders(<ProjectDetailPage />, { role: "SA" });
    await screen.findByRole("heading", { level: 1 });
    expect(id).toBe("abc-123");
  });
});

describe("Detail proyek — informasi", () => {
  it("menampilkan header, PIC, SA, tanggal, tag, dan tautan cepat", async () => {
    setup("Lead_SA", { dq_number: "DQ-77" });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
    expect(screen.getByText("PT ACME")).toBeInTheDocument();
    expect(screen.getByText(DETAIL_ID)).toBeInTheDocument();
    expect(screen.getByText(/Terakhir Diubah: 2 Jan 2025/)).toBeInTheDocument();
    expect(screen.getByText("Sales Demo")).toBeInTheDocument();
    // "SA Demo" tampil di baris info dan di section Tim SA (SA utama).
    await screen.findByRole("listitem", { name: "SA utama: SA Demo" });
    expect(screen.getAllByText("SA Demo")).toHaveLength(2);
    expect(screen.getByText("DQ-77")).toBeInTheDocument();
    expect(screen.getByText("31 Desember 2025")).toBeInTheDocument();
    expect(screen.getByText("Cloud Migration")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dokumen/ })).toHaveAttribute("href", `/projects/${DETAIL_ID}/documents`);
    expect(screen.getByRole("link", { name: /Riwayat Log/ })).toHaveAttribute("href", `/projects/${DETAIL_ID}/activity-logs`);
  });

  it("menampilkan Lead SA dan section penggantian orang", async () => {
    setup("Lead_SA", { lead_sa: { id: "l1", name: "Lead Demo", email: "l@example.com" } });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
    expect(screen.getByText("Lead SA:")).toBeInTheDocument();
    expect(screen.getByText("Lead Demo")).toBeInTheDocument();
    expect(screen.getByText(`Stub orang: ${DETAIL_ID}`)).toBeInTheDocument();
  });

  it("Lead SA belum terisi tampil sebagai 'Belum ada'", async () => {
    setup("Lead_SA", { lead_sa: null });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
    expect(screen.getByText("Belum ada")).toBeInTheDocument();
  });

  it("menampilkan Dibuat oleh, Product PIC, dan Sales PIC", async () => {
    setup("Lead_SA", {
      created_by: { id: "c1", name: "Pembuat Demo", email: "c@example.com" },
      product_pic: { id: "p1", name: "Product Demo", email: "p@example.com" },
    });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
    expect(screen.getByText("Pembuat Demo")).toBeInTheDocument();
    expect(screen.getByText("Product Demo")).toBeInTheDocument();
    expect(screen.getByText("Sales Demo")).toBeInTheDocument();
  });

  it("proyek tanpa Sales: Sales PIC tampil placeholder tanpa error", async () => {
    setup("Lead_SA", {
      product_pic: { id: "p1", name: "Product Demo", email: "p@example.com" },
      sales_pic: null,
    });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });
    expect(screen.getByText("Sales PIC:").nextElementSibling).toHaveTextContent("—");
  });

  it("nilai kosong: placeholder, tanpa tag, tanpa target", async () => {
    setup("Lead_SA", {
      sales_pic: { id: null, name: null, email: null },
      assigned_sa: null,
      dq_number: null,
      target_submit: null,
      use_case_tags: [],
    });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("Belum di-assign")).toBeInTheDocument();
    expect(screen.getByText("Belum diinput")).toBeInTheDocument();
    expect(screen.queryByText("Use Case Tags:")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("meneruskan collaborators dan source document ke section", async () => {
    setup("Lead_SA", {
      collaborators: [{ id: "c1" }, { id: "c2" }],
      source_documents: [makeSourceDoc({ filename: "rfp-acme.pdf", doc_type: "RFP" })],
    });
    expect(await screen.findByText("Stub kolaborator: 2")).toBeInTheDocument();
    expect(screen.getByText("rfp-acme.pdf")).toBeInTheDocument();
    expect(screen.getByText("Stub kualifikasi")).toBeInTheDocument();
  });

  it("tanpa source_documents tidak menampilkan section Source Document", async () => {
    setup("Lead_SA", { source_documents: undefined });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Source Document")).not.toBeInTheDocument();
  });

  it.each([
    ["Won", "bg-emerald-100"],
    ["Lost", "bg-red-100"],
    ["Submitted", "bg-green-100"],
    ["Assigned", "bg-blue-100"],
    ["Awaiting Assignment", "bg-yellow-100"],
    ["Intake", "bg-neutral-100"],
    ["In Progress", "bg-indigo-100"],
    ["Handed Over", "bg-teal-100"],
    ["Closed", "bg-slate-200"],
    ["On Hold", "bg-amber-100"],
  ])("badge status %s berwarna %s", async (status, kelas) => {
    setup("Sales", { status });
    const badge = await screen.findByText(status, { selector: "span" });
    expect(badge.className).toContain(kelas);
  });

  it("Intake menampilkan badge qualification_state di samping status", async () => {
    setup("Sales", { status: "Intake", qualification_state: "Need Clarification" });
    expect(await screen.findByText("Need Clarification", { selector: "span" })).toHaveAttribute("title", "Kualifikasi: Need Clarification");
    expect(screen.getByText("Intake", { selector: "span" })).toBeInTheDocument();
  });

  it("di luar Intake qualification_state tidak ditampilkan", async () => {
    setup("Sales", { status: "Awaiting Assignment", qualification_state: "Qualified" });
    await screen.findByText("Awaiting Assignment", { selector: "span" });
    expect(screen.queryByText("Qualified", { selector: "span" })).not.toBeInTheDocument();
  });
});

describe("Detail proyek — status BANT", () => {
  it("skor >= 60: BANT Passed", async () => {
    setup("Sales", { bant_score: 60 });
    expect(await screen.findByText("BANT Passed, waiting for assignment")).toBeInTheDocument();
  });

  it("skor < 60: BANT not passed", async () => {
    setup("Sales", { bant_score: 59 });
    expect(await screen.findByText("BANT not passed, please refine your input")).toBeInTheDocument();
  });

  it("skor 0 tetap ditampilkan sebagai not passed", async () => {
    setup("Sales", { bant_score: 0 });
    expect(await screen.findByText("BANT not passed, please refine your input")).toBeInTheDocument();
  });

  it("skor null: blok BANT tidak tampil", async () => {
    setup("Sales", { bant_score: null });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText(/BANT/)).not.toBeInTheDocument();
  });
});

describe("Detail proyek — kontrol per peran dan status", () => {
  it.each(["Sales", "Product", "SA"] as const)("%s tidak melihat Hapus, Assign SA, Reassign, maupun Override", async (role) => {
    setup(role, { status: "Awaiting Assignment" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Hapus" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign SA" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reassign SA" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Override skor BANT" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("tanpa user terautentikasi: tidak ada kontrol privileged", async () => {
    setup(undefined, { status: "Intake", qualification_state: "Need Clarification" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Hapus" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Override skor BANT" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign SA" })).not.toBeInTheDocument();
  });

  it.each(["Lead_SA", "Admin"] as const)("%s melihat Hapus dan Edit", async (role) => {
    setup(role);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("button", { name: "Hapus" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it.each(["Lead_SA", "Admin"] as const)("%s melihat Assign SA hanya pada status Awaiting Assignment", async (role) => {
    setup(role, { status: "Awaiting Assignment", assigned_sa: null });
    expect(await screen.findByRole("button", { name: "Assign SA" })).toBeInTheDocument();
  });

  it("Assign SA tidak muncul pada status selain Awaiting Assignment", async () => {
    setup("Lead_SA", { status: "Assigned" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Assign SA" })).not.toBeInTheDocument();
  });

  it.each(["Awaiting Assignment", "Assigned", "In Progress", "Submitted"])("Reassign SA muncul untuk Lead_SA pada status %s bila sudah ada SA", async (status) => {
    setup("Lead_SA", { status });
    expect(await screen.findByRole("button", { name: "Reassign SA" })).toBeInTheDocument();
  });

  it.each(["Intake", "Won", "Handed Over", "Closed", "Lost", "On Hold"])("Reassign SA tidak muncul pada status %s", async (status) => {
    setup("Lead_SA", { status });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Reassign SA" })).not.toBeInTheDocument();
  });

  it("Reassign SA tidak muncul bila belum ada SA", async () => {
    setup("Lead_SA", { status: "Assigned", assigned_sa: null });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Reassign SA" })).not.toBeInTheDocument();
  });

  it.each(["Need Clarification", "Manual Review"])("Override skor BANT muncul untuk Lead_SA pada Intake dengan qualification_state %s", async (qualification_state) => {
    setup("Lead_SA", { status: "Intake", qualification_state });
    expect(await screen.findByRole("button", { name: "Override skor BANT" })).toBeInTheDocument();
  });

  it("Override skor BANT tidak muncul pada status Assigned", async () => {
    setup("Lead_SA", { status: "Assigned", qualification_state: "Qualified" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Override skor BANT" })).not.toBeInTheDocument();
  });

  it("Edit menavigasi ke halaman edit", async () => {
    const { user } = setup("Sales");
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    expect(router.push).toHaveBeenCalledWith(`/projects/${DETAIL_ID}/edit`);
  });
});

describe("Detail proyek — subtask per peran", () => {
  it("Sales tidak melihat section Subtask; SA dan Lead_SA melihat", async () => {
    setup("Sales");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("heading", { name: "Subtask" })).not.toBeInTheDocument();
  });

  it.each(["SA", "Lead_SA", "Admin"] as const)("%s melihat section Subtask", async (role) => {
    setup(role);
    expect(await screen.findByRole("heading", { name: "Subtask" })).toBeInTheDocument();
  });
});

describe("Detail proyek — Tim SA", () => {
  it.each(["Sales", "Product", "SA", "Lead_SA", "Admin"] as const)("%s melihat section Tim SA dengan SA utama", async (role) => {
    setup(role);
    expect(await screen.findByRole("heading", { name: "Tim SA" })).toBeInTheDocument();
    expect(await screen.findByRole("listitem", { name: "SA utama: SA Demo" })).toBeInTheDocument();
  });

  it("hanya Lead_SA/Admin yang melihat kontrol kelola tim", async () => {
    const { unmount } = setup("SA");
    await screen.findByRole("listitem", { name: "SA utama: SA Demo" });
    expect(screen.queryByRole("button", { name: "+ Tambah SA" })).not.toBeInTheDocument();
    unmount();
    setup("Lead_SA");
    expect(await screen.findByRole("button", { name: "+ Tambah SA" })).toBeInTheDocument();
  });
});

describe("Detail proyek — override BANT terpasang", () => {
  it("Lead_SA dapat meng-override dari halaman detail", async () => {
    let body: unknown;
    server.use(
      http.post(api(`/projects/${DETAIL_ID}/score-manual`), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope({ total_score: 72, sub_scores: {}, status: "Awaiting Assignment" }));
      }),
    );
    const { user } = setup("Lead_SA", { status: "Intake", qualification_state: "Need Clarification" });
    await user.click(await screen.findByRole("button", { name: "Override skor BANT" }));
    await user.type(screen.getByLabelText(/Alasan override/), "Konfirmasi manual");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));
    await waitFor(() => expect(body).toMatchObject({ budget: 18, authority: 18, need: 18, timeline: 18, reason: "Konfirmasi manual" }));
  });
});

describe("Detail proyek — Assign / Reassign", () => {
  it("Assign SA membuka modal dengan data proyek, Tutup menutup, sukses memuat ulang halaman", async () => {
    const loc = stubLocation();
    const { user } = setup("Lead_SA", { status: "Awaiting Assignment", assigned_sa: null, bant_score: null, target_submit: null });
    await user.click(await screen.findByRole("button", { name: "Assign SA" }));
    const modal = screen.getByRole("dialog", { name: "stub assign" });
    expect(modal).toHaveTextContent("Assign Migrasi Cloud ACME bant=0 target=");
    await user.click(within(modal).getByRole("button", { name: "Tutup assign" }));
    expect(screen.queryByRole("dialog", { name: "stub assign" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Assign SA" }));
    await user.click(screen.getByRole("button", { name: "Sukses assign" }));
    expect(loc.reload).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "stub assign" })).not.toBeInTheDocument();
  });

  it("Assign SA meneruskan skor dan target submit bila ada", async () => {
    const { user } = setup("Admin", { status: "Awaiting Assignment", bant_score: 80 });
    await user.click(await screen.findByRole("button", { name: "Assign SA" }));
    expect(screen.getByRole("dialog", { name: "stub assign" })).toHaveTextContent("bant=80 target=2025-12-31");
  });

  it("Reassign SA membuka modal dengan nama SA saat ini; sukses memuat ulang", async () => {
    const loc = stubLocation();
    const { user } = setup("Lead_SA", { status: "Assigned" });
    await user.click(await screen.findByRole("button", { name: "Reassign SA" }));
    const modal = screen.getByRole("dialog", { name: "stub reassign" });
    expect(modal).toHaveTextContent("Reassign dari SA Demo");
    await user.click(within(modal).getByRole("button", { name: "Tutup reassign" }));
    expect(screen.queryByRole("dialog", { name: "stub reassign" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reassign SA" }));
    await user.click(screen.getByRole("button", { name: "Sukses reassign" }));
    expect(loc.reload).toHaveBeenCalledTimes(1);
  });
});

describe("Detail proyek — hapus proyek", () => {
  it("konfirmasi menyebut nama proyek; Batal menutup tanpa request", async () => {
    let dipanggil = false;
    server.use(http.delete(api(`/projects/${DETAIL_ID}`), () => { dipanggil = true; return HttpResponse.json(successEnvelope(null)); }));
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Hapus" }));
    expect(screen.getByRole("heading", { name: "Hapus Proyek" })).toBeInTheDocument();
    expect(screen.getByText("Migrasi Cloud ACME", { selector: "strong" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("heading", { name: "Hapus Proyek" })).not.toBeInTheDocument();
    expect(dipanggil).toBe(false);
  });

  it("konfirmasi Hapus: DELETE dikirim lalu navigasi ke beranda", async () => {
    let metode = "";
    server.use(
      http.delete(api(`/projects/${DETAIL_ID}`), ({ request }) => {
        metode = request.method;
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("Admin");
    await user.click(await screen.findByRole("button", { name: "Hapus" }));
    const dialog = screen.getByRole("heading", { name: "Hapus Proyek" }).parentElement as HTMLElement;
    await user.click(within(dialog).getByRole("button", { name: "Hapus" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(metode).toBe("DELETE");
    expect(screen.queryByRole("heading", { name: "Hapus Proyek" })).not.toBeInTheDocument();
  });

  it("gagal hapus: alert, tidak navigasi, modal tertutup", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    server.use(http.delete(api(`/projects/${DETAIL_ID}`), () => HttpResponse.json(errorEnvelope("Forbidden"), { status: 403 })));
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Hapus" }));
    const dialog = screen.getByRole("heading", { name: "Hapus Proyek" }).parentElement as HTMLElement;
    await user.click(within(dialog).getByRole("button", { name: "Hapus" }));
    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith("Gagal menghapus proyek. Silakan coba lagi."));
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Hapus Proyek" })).not.toBeInTheDocument();
  });

  it("saat menghapus tombol menjadi 'Menghapus...' dan tombol dinonaktifkan", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.delete(api(`/projects/${DETAIL_ID}`), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Hapus" }));
    const dialog = screen.getByRole("heading", { name: "Hapus Proyek" }).parentElement as HTMLElement;
    await user.click(within(dialog).getByRole("button", { name: "Hapus" }));
    expect(await screen.findByRole("button", { name: "Menghapus..." })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Batal" })).toBeDisabled();
    lepas();
    await waitFor(() => expect(router.push).toHaveBeenCalled());
  });
});

describe("Detail proyek — handover Won", () => {
  function serveHandover(status: Record<string, unknown>) {
    server.use(
      http.get(api(`/projects/${DETAIL_ID}/handover-status`), () =>
        HttpResponse.json(successEnvelope(makeHandoverReadiness({ pmo_email: null, delivery_email: null, ...status }))),
      ),
    );
  }

  it("SA melihat modal handover pada Won dan dapat menutupnya", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    const { user } = setup("SA", { status: "Won" });
    const modal = await screen.findByRole("dialog", { name: "stub handover" });
    expect(modal).toHaveTextContent("Handover Migrasi Cloud ACME");
    await user.click(within(modal).getByRole("button", { name: "Ack handover" }));
    expect(screen.queryByRole("dialog", { name: "stub handover" })).not.toBeInTheDocument();
  });

  it("Admin (SA dengan is_admin) tetap melihat modal handover sebagai SA", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    setup("Admin", { status: "Won" });
    expect(await screen.findByRole("dialog", { name: "stub handover" })).toBeInTheDocument();
  });

  it.each(["Sales", "Product", "Lead_SA"] as const)("%s tidak melihat modal handover", async (role) => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    setup(role, { status: "Won" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("dialog", { name: "stub handover" })).not.toBeInTheDocument();
  });

  it("modal handover tidak muncul bila status bukan Won", async () => {
    setup("SA", { status: "Assigned" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("dialog", { name: "stub handover" })).not.toBeInTheDocument();
  });

  it("form konfigurasi handover muncul bila email PMO/Delivery belum lengkap", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: null });
    setup("Lead_SA", { status: "Won" });
    expect(await screen.findByText("Konfigurasi Handover")).toBeInTheDocument();
    expect(screen.getByText("Email PMO Lead dan Delivery Lead belum dikonfigurasi.")).toBeInTheDocument();
    expect(screen.getByText("Stub config form pmo=pmo@x delivery=-")).toBeInTheDocument();
  });

  it("form konfigurasi handover tidak muncul bila email sudah lengkap", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    setup("Lead_SA", { status: "Won" });
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(screen.queryByText("Konfigurasi Handover")).not.toBeInTheDocument());
  });

  it("handover-status gagal dimuat: pesan error di bagian Handover (form konfigurasi tidak hilang diam-diam), coba lagi memuat ulang", async () => {
    server.use(
      gagalLaluBerhasil(`/projects/${DETAIL_ID}/handover-status`, makeHandoverReadiness({ pmo_email: null, delivery_email: null })),
    );
    const { user } = setup("Lead_SA", { status: "Won" });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat status handover.");
    expect(screen.queryByText("Stub config form pmo=- delivery=-")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("Stub config form pmo=- delivery=-")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("tombol Handover pada Won: sukses memuat ulang detail sehingga status menjadi Handed Over dan tombol hilang", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    let handedOver = false;
    server.use(
      http.get(api(`/projects/${DETAIL_ID}`), () =>
        HttpResponse.json(successEnvelope(makeProjectDetail({ status: handedOver ? "Handed Over" : "Won" }))),
      ),
      http.post(api(`/projects/${DETAIL_ID}/handover`), () => {
        handedOver = true;
        return HttpResponse.json(successEnvelope({ new_status: "Handed Over" }));
      }),
    );
    const { user } = renderWithProviders(<ProjectDetailPage />, { role: "Lead_SA" });
    await user.click(await screen.findByRole("button", { name: "Handover" }));
    const dialog = await screen.findByRole("dialog", { name: "Handover Proyek" });
    const kirim = within(dialog).getByRole("button", { name: "Konfirmasi Handover" });
    await waitFor(() => expect(kirim).toBeEnabled());
    await user.click(kirim);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument());
    expect(screen.queryByRole("dialog", { name: "Handover Proyek" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Handed Over").length).toBeGreaterThan(0);
  });

  it("Sales tidak melihat tombol Handover pada Won", async () => {
    serveHandover({ pmo_email: "pmo@x", delivery_email: "d@x" });
    setup("Sales", { status: "Won" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Handover" })).not.toBeInTheDocument();
  });

  it("handover-status tidak diminta bila bukan Won", async () => {
    let dipanggil = false;
    server.use(http.get(api(`/projects/${DETAIL_ID}/handover-status`), () => { dipanggil = true; return HttpResponse.json(successEnvelope({})); }));
    setup("Lead_SA", { status: "Assigned" });
    await screen.findByRole("heading", { level: 1 });
    expect(dipanggil).toBe(false);
  });
});

describe("Detail proyek — Project Story", () => {
  function serveStory(items: unknown[], total = items.length) {
    server.use(http.get(api(`/projects/${DETAIL_ID}/story`), () => HttpResponse.json(successEnvelope({ items, total }))));
  }

  it("keadaan kosong: pesan dan tanpa tombol Summarize", async () => {
    // Default global (grup operations) berisi activity log; test ini butuh story kosong.
    serveStory([]);
    setup("Lead_SA");
    expect(await screen.findByText("Belum ada activity log untuk proyek ini.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Summarize" })).not.toBeInTheDocument();
  });

  it("story gagal dimuat: pesan error (bukan 'Belum ada activity log'), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil(`/projects/${DETAIL_ID}/story`, { items: [makeStoryItem({ raw_notes: "catatan pulih" })], total: 1 }));
    const { user } = setup("Lead_SA");

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat activity log proyek.");
    expect(screen.queryByText("Belum ada activity log untuk proyek ini.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("catatan pulih")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("skeleton saat memuat story", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api(`/projects/${DETAIL_ID}/story`), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope({ items: [], total: 0 }));
      }),
    );
    const { container } = setup("Lead_SA");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Project Story")).not.toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    lepas();
    expect(await screen.findByText("Project Story")).toBeInTheDocument();
  });

  it("menampilkan log, kategori, jam, dan action item dengan PIC", async () => {
    serveStory([
      makeStoryItem({
        ai_polished_notes: {
          discussion_points: [],
          action_items: [{ description: "Kirim proposal", pic: "Andi" }, { description: "Review HLD", pic: null }],
        },
      }),
      makeStoryItem({ id_log: "log-2", subtask_category: "Demo", duration_hours: 1.5, raw_notes: "Demo produk" }),
    ]);
    setup("SA");
    expect(await screen.findByText("Diskusi arsitektur")).toBeInTheDocument();
    expect(screen.getByText("Workshop")).toBeInTheDocument();
    expect(screen.getByText("2h")).toBeInTheDocument();
    expect(screen.getByText("1.5h")).toBeInTheDocument();
    expect(screen.getByText("Kirim proposal")).toBeInTheDocument();
    expect(screen.getByText("(PIC: Andi)")).toBeInTheDocument();
    expect(screen.getByText("Review HLD")).toBeInTheDocument();
    expect(screen.getByText("2 aktivitas — menampilkan 5 terbaru")).toBeInTheDocument();
  });

  it("tautan Lihat Semua hanya bila total > 5", async () => {
    serveStory([makeStoryItem()], 6);
    setup("SA");
    const link = await screen.findByRole("link", { name: "Lihat Semua (6)" });
    expect(link).toHaveAttribute("href", `/projects/${DETAIL_ID}/activity-logs`);
  });

  it("tanpa Lihat Semua bila total <= 5", async () => {
    serveStory([makeStoryItem()], 5);
    setup("SA");
    await screen.findByText("Diskusi arsitektur");
    expect(screen.queryByRole("link", { name: /Lihat Semua/ })).not.toBeInTheDocument();
  });

  it("Summarize sukses menampilkan ringkasan dan 'Generating...' saat berjalan", async () => {
    serveStory([makeStoryItem()]);
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.post(api(`/projects/${DETAIL_ID}/summarize`), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope({ summary: "Proyek berjalan lancar.", total_activities: 1, total_hours: 2 }));
      }),
    );
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Summarize" }));
    expect(await screen.findByRole("button", { name: "Generating..." })).toBeDisabled();
    lepas();
    expect(await screen.findByText("Proyek berjalan lancar.")).toBeInTheDocument();
    expect(screen.getByText("Ringkasan Proyek")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Summarize" })).toBeEnabled();
  });

  it("Summarize gagal menampilkan pesan gagal", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    serveStory([makeStoryItem()]);
    server.use(http.post(api(`/projects/${DETAIL_ID}/summarize`), () => HttpResponse.json(errorEnvelope("LLM down"), { status: 502 })));
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Summarize" }));
    expect(await screen.findByText("Gagal menghasilkan ringkasan. Silakan coba lagi.")).toBeInTheDocument();
  });
});

describe("Detail proyek — aksi status terpasang", () => {
  it("Lead_SA pada Submitted melihat aksi status; konfirmasi mengirim PATCH lalu memuat ulang detail", async () => {
    let patch: unknown;
    let jumlahGetDetail = 0;
    server.use(
      http.get(api("/projects/:id"), () => {
        jumlahGetDetail += 1;
        return HttpResponse.json(successEnvelope(makeProjectDetail({ status: jumlahGetDetail > 1 ? "Won" : "Submitted" })));
      }),
      http.patch(api(`/projects/${DETAIL_ID}/status`), async ({ request }) => {
        patch = await request.json();
        return HttpResponse.json(successEnvelope({ id_project: DETAIL_ID, old_status: "Submitted", new_status: "Won" }));
      }),
    );
    const { user } = renderWithProviders(<ProjectDetailPage />, { role: "Lead_SA" });
    await user.click(await screen.findByRole("button", { name: "Tandai Won" }));
    await user.click(within(screen.getByRole("dialog", { name: "Tandai Won" })).getByRole("button", { name: "Konfirmasi" }));

    await waitFor(() => expect(patch).toEqual({ new_status: "Won" }));
    expect(await screen.findByText("Won", { selector: "span" })).toBeInTheDocument();
    expect(jumlahGetDetail).toBeGreaterThan(1);
  });

  it("SA ditugaskan pada Assigned melihat Tandai Submitted; Sales PIC tidak", async () => {
    setup("SA", { status: "Assigned", assigned_sa: { id: "00000000-0000-4000-8000-000000000002", name: "SA Demo", email: "sa@example.com" } });
    expect(await screen.findByRole("button", { name: "Tandai Submitted" })).toBeInTheDocument();
  });

  it("Lost menampilkan alasan Lost dan Admin dapat membuka kembali", async () => {
    setup("Admin", { status: "Lost", previous_status: "Submitted", lost_reason: "Customer batal" });
    expect(await screen.findByText(/Customer batal/)).toHaveTextContent("Alasan Lost: Customer batal");
    expect(screen.getByRole("button", { name: "Buka Kembali" })).toBeInTheDocument();
  });

  it("Lead_SA non-admin tidak melihat Buka Kembali pada Closed", async () => {
    setup("Lead_SA", { status: "Closed", previous_status: "Handed Over" });
    await screen.findByText(/read-only/i);
    expect(screen.queryByRole("button", { name: "Buka Kembali" })).not.toBeInTheDocument();
  });
});
