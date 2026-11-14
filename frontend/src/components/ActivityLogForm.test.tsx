import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { makeActivityLog } from "@/test/fixtures/operations";
import { ActivityLogForm } from "./ActivityLogForm";

const projects = [
  { id: "p-1", project_name: "Migrasi Cloud", status: "Intake" },
  { id: "p-2", project_name: "Rollout Jaringan", status: "Handed Over" },
];

function setup(props: Partial<React.ComponentProps<typeof ActivityLogForm>> = {}) {
  const onSuccess = vi.fn();
  const utils = renderWithProviders(<ActivityLogForm projects={projects} onSuccess={onSuccess} {...props} />, { role: "SA" });
  return { onSuccess, ...utils };
}

const project = () => screen.getByLabelText(/^Proyek/);
const phase = () => screen.getByLabelText(/^Fase Proyek/);
const subtask = () => screen.getByLabelText(/^Subtask/);
const duration = () => screen.getByLabelText(/^Durasi/);
const notes = () => screen.getByLabelText(/^Catatan/);
const submit = () => screen.getByRole("button", { name: "Simpan Activity Log" });

function captureCreate() {
  const captured: { body?: unknown; auth?: string | null } = {};
  server.use(
    http.post(api("/activity-logs"), async ({ request }) => {
      captured.body = await request.json();
      captured.auth = request.headers.get("Authorization");
      return HttpResponse.json(successEnvelope(makeActivityLog()), { status: 201 });
    })
  );
  return captured;
}

describe("ActivityLogForm — tampilan awal", () => {
  it("default: work_type Project, durasi 1, daftar subtask proyek, fase Pre-Implementation", () => {
    setup();
    expect(screen.getByRole("form", { name: "Form activity log" })).toBeInTheDocument();
    expect(duration()).toHaveValue(1);
    expect(phase()).toHaveValue("Pre-Implementation");
    expect(project()).toHaveValue("");
    expect(screen.getByRole("option", { name: "Assessment" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Training" })).not.toBeInTheDocument();
    expect(screen.getByText("0/5000")).toBeInTheDocument();
  });

  it("defaultProjectId memilih proyek otomatis dan fase dari status (Handed Over → Implementation)", () => {
    setup({ defaultProjectId: "p-2" });
    expect(project()).toHaveValue("p-2");
    expect(phase()).toHaveValue("Implementation");
  });

  it("defaultProjectId yang tidak ada di daftar diabaikan", () => {
    setup({ defaultProjectId: "tidak-ada" });
    expect(project()).toHaveValue("");
  });

  it("memilih proyek menyesuaikan fase default dari status proyek", async () => {
    const { user } = setup();
    await user.selectOptions(project(), "p-2");
    expect(phase()).toHaveValue("Implementation");
    await user.selectOptions(project(), "p-1");
    expect(phase()).toHaveValue("Pre-Implementation");
  });

  it("fase bisa diubah manual", async () => {
    const { user } = setup();
    await user.selectOptions(phase(), "Post-Implementation");
    expect(phase()).toHaveValue("Post-Implementation");
  });

  it("beralih ke Non-Project menyembunyikan proyek/fase dan mengganti daftar subtask", async () => {
    const { user } = setup();
    await user.selectOptions(subtask(), "Assessment");
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    expect(screen.queryByLabelText(/^Proyek/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Fase Proyek/)).not.toBeInTheDocument();
    expect(subtask()).toHaveValue(""); // pilihan di-reset
    expect(screen.getByRole("option", { name: "Training" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Assessment" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Project" }));
    expect(project()).toBeInTheDocument();
  });
});

describe("ActivityLogForm — validasi", () => {
  it("form kosong (Project): proyek, subtask, dan catatan wajib; tanpa request", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/activity-logs"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup();
    await user.click(submit());
    expect(screen.getByText("Proyek wajib dipilih")).toBeInTheDocument();
    expect(screen.getByText("Subtask wajib dipilih")).toBeInTheDocument();
    expect(screen.getByText("Catatan tidak boleh kosong")).toBeInTheDocument();
    expect(project()).toBeInvalid();
    expect(hit).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("Non-Project: tidak mewajibkan proyek", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    await user.click(submit());
    expect(screen.queryByText("Proyek wajib dipilih")).not.toBeInTheDocument();
    expect(screen.getByText("Subtask wajib dipilih")).toBeInTheDocument();
  });

  it("catatan hanya spasi dianggap kosong", async () => {
    const { user } = setup();
    await user.type(notes(), "    ");
    await user.click(submit());
    expect(screen.getByText("Catatan tidak boleh kosong")).toBeInTheDocument();
  });

  it("durasi kosong menampilkan pesan rentang", async () => {
    const { user } = setup();
    await user.clear(duration());
    await user.click(submit());
    expect(screen.getByText("Durasi harus antara 0.25 - 24 jam")).toBeInTheDocument();
  });

  it("durasi di luar rentang ditahan validasi native (min/max/step) sebelum request", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/activity-logs"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await user.selectOptions(project(), "p-1");
    await user.selectOptions(subtask(), "Assessment");
    await user.type(notes(), "catatan");
    await user.clear(duration());
    await user.type(duration(), "25");
    await user.click(submit());
    expect(duration()).toBeInvalid();
    expect(hit).not.toHaveBeenCalled();
  });

  it("durasi di luar rentang yang lolos ke handler submit tetap ditolak oleh validasi aplikasi", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/activity-logs"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await user.selectOptions(project(), "p-1");
    await user.selectOptions(subtask(), "Assessment");
    await user.type(notes(), "catatan");
    await user.clear(duration());
    await user.type(duration(), "0.1");
    fireEvent.submit(screen.getByRole("form", { name: "Form activity log" })); // melewati validasi native
    expect(await screen.findByText("Durasi harus antara 0.25 - 24 jam")).toBeInTheDocument();
    expect(hit).not.toHaveBeenCalled();
  });

  it("catatan melebihi 5000 karakter (disisipkan tanpa maxLength) ditolak dan penghitung memerah", () => {
    setup();
    fireEvent.change(notes(), { target: { value: "x".repeat(5001) } });
    expect(screen.getByText("5001/5000")).toHaveClass("text-red-600");
    fireEvent.submit(screen.getByRole("form", { name: "Form activity log" }));
    expect(screen.getByText("Catatan maksimal 5000 karakter")).toBeInTheDocument();
  });

  it("textarea membatasi input maksimal 5000 karakter", () => {
    setup();
    expect(notes()).toHaveAttribute("maxlength", "5000");
  });

  it("error per-field hilang begitu field diperbaiki", async () => {
    const { user } = setup();
    await user.click(submit());
    await user.selectOptions(project(), "p-1");
    await user.selectOptions(subtask(), "Assessment");
    await user.type(notes(), "isi");
    expect(screen.queryByText("Proyek wajib dipilih")).not.toBeInTheDocument();
    expect(screen.queryByText("Subtask wajib dipilih")).not.toBeInTheDocument();
    expect(screen.queryByText("Catatan tidak boleh kosong")).not.toBeInTheDocument();
  });

  it("error durasi hilang saat durasi diubah", async () => {
    const { user } = setup();
    await user.clear(duration());
    await user.click(submit());
    expect(screen.getByText("Durasi harus antara 0.25 - 24 jam")).toBeInTheDocument();
    await user.type(duration(), "2");
    expect(screen.queryByText("Durasi harus antara 0.25 - 24 jam")).not.toBeInTheDocument();
  });

  it("berganti work_type menghapus semua error", async () => {
    const { user } = setup();
    await user.click(submit());
    expect(screen.getByText("Proyek wajib dipilih")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    expect(screen.queryByText("Subtask wajib dipilih")).not.toBeInTheDocument();
  });
});

describe("ActivityLogForm — submit", () => {
  async function fillProject(user: ReturnType<typeof setup>["user"]) {
    await user.selectOptions(project(), "p-1");
    await user.selectOptions(subtask(), "Customer Meeting");
    await user.clear(duration());
    await user.type(duration(), "2.5");
    await user.type(notes(), "  Bahas arsitektur  ");
  }

  it("sukses (Project): mengirim body lengkap + token, menampilkan toast, mereset form, memanggil onSuccess", async () => {
    const captured = captureCreate();
    const { user, onSuccess } = setup();
    await fillProject(user);
    await user.click(submit());

    expect(await screen.findByRole("alert")).toHaveTextContent("Activity log berhasil disimpan");
    expect(captured.body).toEqual({
      work_type: "Project",
      subtask_category: "Customer Meeting",
      duration_hours: 2.5,
      raw_notes: "Bahas arsitektur",
      id_project: "p-1",
      project_phase: "Pre-Implementation",
    });
    expect(captured.auth).toBe("Bearer access-SA");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(project()).toHaveValue("");
    expect(subtask()).toHaveValue("");
    expect(duration()).toHaveValue(1);
    expect(notes()).toHaveValue("");
  });

  it("sukses (Non-Project): body tanpa id_project dan project_phase", async () => {
    const captured = captureCreate();
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    await user.selectOptions(subtask(), "Training");
    await user.type(notes(), "Ikut pelatihan");
    await user.click(submit());
    await screen.findByText("Activity log berhasil disimpan");
    expect(captured.body).toEqual({
      work_type: "Non-Project",
      subtask_category: "Training",
      duration_hours: 1,
      raw_notes: "Ikut pelatihan",
    });
  });

  it("setelah reset, proyek kembali ke defaultProjectId", async () => {
    captureCreate();
    const { user } = setup({ defaultProjectId: "p-2" });
    await user.selectOptions(subtask(), "Assessment");
    await user.type(notes(), "x");
    await user.click(submit());
    await screen.findByText("Activity log berhasil disimpan");
    expect(project()).toHaveValue("p-2");
    expect(phase()).toHaveValue("Implementation");
  });

  it("menampilkan action items dari AI polishing (dengan PIC) dan bisa ditutup", async () => {
    server.use(
      http.post(api("/activity-logs"), () =>
        HttpResponse.json(
          successEnvelope({
            ai_polished_notes: {
              discussion_points: ["a"],
              action_items: [{ description: "Kirim proposal", pic: "Budi" }, { description: "Jadwalkan demo", pic: null }],
            },
          })
        )
      )
    );
    const { user } = setup();
    await fillProject(user);
    await user.click(submit());
    expect(await screen.findByRole("heading", { name: "Action Items" })).toBeInTheDocument();
    expect(screen.getByText("Kirim proposal")).toBeInTheDocument();
    expect(screen.getByText("(PIC: Budi)")).toBeInTheDocument();
    expect(screen.getByText("Jadwalkan demo")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tutup" }));
    expect(screen.queryByRole("heading", { name: "Action Items" })).not.toBeInTheDocument();
  });

  it("tidak menampilkan panel action items bila AI polishing kosong, dan membersihkan panel lama", async () => {
    server.use(
      http.post(api("/activity-logs"), () =>
        HttpResponse.json(successEnvelope({ ai_polished_notes: { discussion_points: [], action_items: [{ description: "Satu" }] } })), { once: true }
      )
    );
    const { user } = setup();
    await fillProject(user);
    await user.click(submit());
    expect(await screen.findByText("Satu")).toBeInTheDocument();

    await fillProject(user); // submit kedua memakai handler default (tanpa action items)
    await user.click(submit());
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Action Items" })).not.toBeInTheDocument());
  });

  it("selama request: tombol 'Menyimpan...' dan semua kontrol nonaktif", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/activity-logs"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user, onSuccess } = setup();
    await fillProject(user);
    await user.click(submit());
    expect(await screen.findByRole("button", { name: /Menyimpan/ })).toBeDisabled();
    expect(project()).toBeDisabled();
    expect(notes()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Non-Project" })).toBeDisabled();
    release();
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("error server: toast error berisi pesan backend, form tidak direset, onSuccess tidak dipanggil", async () => {
    server.use(http.post(api("/activity-logs"), () => HttpResponse.json(errorEnvelope("Anda bukan anggota proyek ini"), { status: 403 })));
    const { user, onSuccess } = setup();
    await fillProject(user);
    await user.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Anda bukan anggota proyek ini");
    expect(notes()).toHaveValue("  Bahas arsitektur  ");
    expect(onSuccess).not.toHaveBeenCalled();
    expect(submit()).toBeEnabled();
  });

  it("toast hilang otomatis setelah 3 detik", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    captureCreate();
    const { user } = setup();
    await fillProject(user);
    await user.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Activity log berhasil disimpan");
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
