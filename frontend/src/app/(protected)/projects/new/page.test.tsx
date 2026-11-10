import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay } from "msw";
import { describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, router, server, successEnvelope } from "@/test";
import { makeOpportunitySchema } from "@/test/fixtures/opportunity";
import { makeCreateProjectResponse } from "@/test/fixtures/projects";
import NewProjectPage from "./page";

const PDF = "application/pdf";

function useSchema() {
  server.use(http.get(api("/qualification/schema"), () => HttpResponse.json(successEnvelope(makeOpportunitySchema()))));
}

/** Tangkap permintaan POST /projects (multipart) dan balas dengan `respond`. */
function capturePost(respond: () => Response | Promise<Response>) {
  const captured: { form?: FormData } = {};
  server.use(
    http.post(api("/projects"), async ({ request }) => {
      captured.form = await request.formData();
      return respond();
    }),
  );
  return captured;
}

/**
 * Tangkap POST /projects di batas `fetch` untuk permintaan yang memuat FILE: jsdom File di dalam
 * jsdom FormData tidak bisa diserialisasi fetch bawaan Node (undici) — keterbatasan lingkungan test,
 * bukan bug aplikasi. Permintaan lain tetap diteruskan ke MSW.
 */
function captureFetchPost(response: unknown) {
  const captured: { form?: FormData; headers?: Record<string, string> } = {};
  const asli = globalThis.fetch;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (init?.method === "POST" && url === api("/projects")) {
      captured.form = init.body as FormData;
      captured.headers = init.headers as Record<string, string>;
      return Response.json(successEnvelope(response), { status: 201 });
    }
    return asli(input, init);
  });
  return captured;
}

const created = (overrides: Record<string, unknown> = {}) =>
  HttpResponse.json(successEnvelope(makeCreateProjectResponse(overrides)), { status: 201 });

function setup(opts: { fake?: boolean } = {}) {
  if (opts.fake) vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup(opts.fake ? { advanceTimers: (ms) => vi.advanceTimersByTime(ms) } : undefined);
  renderWithProviders(<NewProjectPage />, { role: "Sales" });
  return user;
}

async function isiLangkah1(user: ReturnType<typeof userEvent.setup>, o: { dq?: string } = {}) {
  await user.type(screen.getByLabelText(/Nama Proyek/), "  Migrasi DWH ");
  await user.type(screen.getByLabelText(/Nama Customer/), "PT Contoh");
  fireEvent.change(screen.getByLabelText(/Target Submit/), { target: { value: "2099-12-31" } });
  await user.type(screen.getByLabelText(/Estimasi Nilai Proyek/), "1500000");
  if (o.dq) await user.type(screen.getByLabelText(/DQ Number/), o.dq);
}

const lanjut = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole("button", { name: "Lanjut ke Kuesioner" }));

async function isiKuesioner(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(/Anggaran bulanan/), "50");
  await user.selectOptions(screen.getByLabelText(/Status anggaran/), "Sudah disetujui");
  await user.type(screen.getByLabelText(/Nama PIC/), "Budi");
  await user.type(screen.getByLabelText(/Kebutuhan teknis/), "Migrasi data warehouse");
}

describe("NewProjectPage — langkah 1", () => {
  it("menampilkan header langkah 1 dari 2 dengan form data dasar dan upload file", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Request SA" })).toBeInTheDocument();
    expect(screen.getByText(/Langkah 1 dari 2 — Data dasar dan file/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Area upload file/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lanjut ke Kuesioner" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kembali" })).not.toBeInTheDocument();
  });

  it("menampilkan error wajib diisi untuk semua field wajib dan tetap di langkah 1", async () => {
    const user = setup();
    await lanjut(user);
    expect(screen.getByText("Nama proyek wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Nama customer wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Target submit wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Estimasi nilai proyek wajib diisi")).toBeInTheDocument();
    expect(screen.getByLabelText(/Nama Proyek/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Langkah 1 dari 2/)).toBeInTheDocument();
  });

  it("menghapus pesan error field saat pengguna mulai mengetik", async () => {
    const user = setup();
    await lanjut(user);
    await user.type(screen.getByLabelText(/Nama Proyek/), "A");
    expect(screen.queryByText("Nama proyek wajib diisi")).not.toBeInTheDocument();
    expect(screen.getByText("Nama customer wajib diisi")).toBeInTheDocument();
  });

  it("menolak nama proyek/customer lebih dari 150 karakter", async () => {
    const user = setup();
    fireEvent.change(screen.getByLabelText(/Nama Proyek/), { target: { value: "x".repeat(151) } });
    fireEvent.change(screen.getByLabelText(/Nama Customer/), { target: { value: "y".repeat(151) } });
    await lanjut(user);
    expect(screen.getByText("Nama proyek maksimal 150 karakter")).toBeInTheDocument();
    expect(screen.getByText("Nama customer maksimal 150 karakter")).toBeInTheDocument();
  });

  it("menampilkan penghitung karakter nama proyek dan customer", async () => {
    const user = setup();
    await user.type(screen.getByLabelText(/Nama Proyek/), "abc");
    await user.type(screen.getByLabelText(/Nama Customer/), "de");
    expect(screen.getByText("3/150 karakter")).toBeInTheDocument();
    expect(screen.getByText("2/150 karakter")).toBeInTheDocument();
  });

  it("menolak target submit di masa lalu", async () => {
    const user = setup();
    fireEvent.change(screen.getByLabelText(/Target Submit/), { target: { value: "2020-01-01" } });
    await lanjut(user);
    expect(screen.getByText("Target submit tidak boleh tanggal di masa lalu")).toBeInTheDocument();
  });

  it("memformat estimasi nilai dengan pemisah ribuan dan membuang karakter non-angka", async () => {
    const user = setup();
    const input = screen.getByLabelText(/Estimasi Nilai Proyek/);
    await user.type(input, "1a2b3456789");
    expect(input).toHaveValue("123.456.789");
    await user.clear(input);
    expect(input).toHaveValue("");
  });

  it("menolak estimasi nilai di bawah Rp 1 dan di atas batas maksimal", async () => {
    const user = setup();
    const input = screen.getByLabelText(/Estimasi Nilai Proyek/);
    await user.type(input, "0");
    await lanjut(user);
    expect(screen.getByText("Estimasi nilai minimal Rp 1")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "1000000000000");
    await lanjut(user);
    expect(screen.getByText("Estimasi nilai maksimal Rp 999.999.999.999")).toBeInTheDocument();
  });

  it("DQ Number opsional, tetapi bila diisi harus alfanumerik+hyphen 5–20 karakter", async () => {
    const user = setup();
    await isiLangkah1(user, { dq: "ab" });
    await lanjut(user);
    expect(screen.getByText(/Format DQ Number tidak valid/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/DQ Number/));
    await user.type(screen.getByLabelText(/DQ Number/), "DQ-2025-00123");
    await lanjut(user);
    expect(screen.getByText(/Langkah 2 dari 2/)).toBeInTheDocument();
  });

  it("mewajibkan tipe MoM/RFP untuk setiap file valid; file tak valid tidak dihitung", async () => {
    const user = setup();
    await isiLangkah1(user);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "mom.pdf", { type: PDF }));
    await lanjut(user);
    expect(screen.getByText("Pilih tipe (MoM atau RFP) untuk setiap file")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Tipe dokumen mom.pdf"), "MoM");
    expect(screen.queryByText("Pilih tipe (MoM atau RFP) untuk setiap file")).not.toBeInTheDocument();
    await lanjut(user);
    expect(screen.getByText(/Langkah 2 dari 2/)).toBeInTheDocument();
  });

  it("menghapus pesan error file begitu daftar file berubah", async () => {
    const user = setup();
    await isiLangkah1(user);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "mom.pdf", { type: PDF }));
    await lanjut(user);
    await user.click(screen.getByRole("button", { name: "Hapus file mom.pdf" }));
    expect(screen.queryByText("Pilih tipe (MoM atau RFP) untuk setiap file")).not.toBeInTheDocument();
  });
});

describe("NewProjectPage — langkah 2 dan navigasi", () => {
  it("berpindah ke langkah 2 dan merender kuesioner dari skema backend", async () => {
    useSchema();
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    expect(screen.getByText(/Langkah 2 dari 2 — Kuesioner kualifikasi/)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Budget" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit Request" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kembali" })).toBeInTheDocument();
  });

  it("menampilkan status memuat kuesioner, lalu form begitu skema tiba", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api("/qualification/schema"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(makeOpportunitySchema()));
      }),
    );
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    expect(screen.getByRole("status")).toHaveTextContent("Memuat kuesioner...");
    lepas();
    expect(await screen.findByLabelText(/Anggaran bulanan/)).toBeInTheDocument();
  });

  it("menampilkan pesan gagal bila skema kuesioner tidak dapat dimuat", async () => {
    server.use(http.get(api("/qualification/schema"), () => HttpResponse.json(errorEnvelope("boom"), { status: 500 })));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    expect(await screen.findByText("Gagal memuat kuesioner. Muat ulang halaman.")).toBeInTheDocument();
  });

  it("kembali ke langkah 1 dan maju lagi tanpa kehilangan isian langkah 1 maupun jawaban kuesioner", async () => {
    useSchema();
    const user = setup();
    await isiLangkah1(user, { dq: "DQ-2025-001" });
    await lanjut(user);
    await isiKuesioner(user);

    await user.click(screen.getByRole("button", { name: "Kembali" }));
    expect(screen.getByText(/Langkah 1 dari 2/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Nama Proyek/)).toHaveValue("  Migrasi DWH ");
    expect(screen.getByLabelText(/Nama Customer/)).toHaveValue("PT Contoh");
    expect(screen.getByLabelText(/Target Submit/)).toHaveValue("2099-12-31");
    expect(screen.getByLabelText(/Estimasi Nilai Proyek/)).toHaveValue("1.500.000");
    expect(screen.getByLabelText(/DQ Number/)).toHaveValue("DQ-2025-001");

    await lanjut(user);
    expect(await screen.findByLabelText(/Anggaran bulanan/)).toHaveValue(50);
    expect(screen.getByLabelText(/Status anggaran/)).toHaveValue("Sudah disetujui");
    expect(screen.getByLabelText(/Nama PIC/)).toHaveValue("Budi");
    expect(screen.getByLabelText(/Kebutuhan teknis/)).toHaveValue("Migrasi data warehouse");
  });

  it("file yang dipilih di langkah 1 tetap ada setelah kembali dan jumlahnya tampil di tombol submit", async () => {
    useSchema();
    const user = setup();
    await isiLangkah1(user);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "rfp.pdf", { type: PDF }));
    await user.selectOptions(screen.getByLabelText("Tipe dokumen rfp.pdf"), "RFP");
    await lanjut(user);
    expect(await screen.findByRole("button", { name: "Submit Request (1 file)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Kembali" }));
    expect(screen.getByText("rfp.pdf")).toBeInTheDocument();
    expect(screen.getByLabelText("Tipe dokumen rfp.pdf")).toHaveValue("RFP");
  });

  it("validasi kuesioner di klien: field wajib kosong menampilkan error dan tidak mengirim permintaan", async () => {
    useSchema();
    let dikirim = false;
    server.use(http.post(api("/projects"), () => ((dikirim = true), created())));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await screen.findByLabelText(/Anggaran bulanan/);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(screen.getAllByText("Wajib diisi").length).toBeGreaterThanOrEqual(3);
    expect(dikirim).toBe(false);
    // mengetik membersihkan error field itu saja
    await user.type(screen.getByLabelText(/Anggaran bulanan/), "50");
    expect(screen.getAllByText("Wajib diisi").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByLabelText(/Anggaran bulanan/)).toHaveAttribute("aria-invalid", "false");
  });

  it("validasi format kuesioner: angka di luar rentang dan teks melebihi panjang maksimal", async () => {
    useSchema();
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.clear(screen.getByLabelText(/Anggaran bulanan/));
    await user.type(screen.getByLabelText(/Anggaran bulanan/), "5000");
    await user.clear(screen.getByLabelText(/Nama PIC/));
    await user.type(screen.getByLabelText(/Nama PIC/), "N".repeat(21));
    await user.type(screen.getByLabelText(/Email PIC/), "bukan-email");
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(screen.getByText("Harus antara 1 dan 1000")).toBeInTheDocument();
    expect(screen.getByText("Maksimal 20 karakter")).toBeInTheDocument();
    expect(screen.getByText("Format email tidak valid")).toBeInTheDocument();
  });

  it("submit sebelum skema selesai dimuat memberi tahu pengguna, tanpa mengirim", async () => {
    server.use(http.get(api("/qualification/schema"), async () => { await delay("infinite"); return HttpResponse.json({}); }));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByText("Skema kuesioner belum dimuat. Muat ulang halaman.")).toBeInTheDocument();
  });
});

describe("NewProjectPage — pengiriman", () => {
  it("mengirim multipart dengan field header, jawaban kuesioner (JSON), dan file+tipe; token disertakan", async () => {
    useSchema();
    const captured = captureFetchPost(makeCreateProjectResponse({ scoring_triggered: true, bant_score: null, sub_scores: null }));
    const user = setup();
    await isiLangkah1(user, { dq: " DQ-2025-001 " });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [new File(["a"], "mom.pdf", { type: PDF }), new File(["b"], "rfp.pdf", { type: PDF })]);
    await user.selectOptions(screen.getByLabelText("Tipe dokumen mom.pdf"), "MoM");
    await user.selectOptions(screen.getByLabelText("Tipe dokumen rfp.pdf"), "RFP");
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request (2 file)" }));

    await screen.findByText(/Proyek berhasil dibuat/);
    const form = captured.form!;
    expect(form.get("project_name")).toBe("Migrasi DWH");
    expect(form.get("customer_name")).toBe("PT Contoh");
    expect(form.get("target_submit")).toBe("2099-12-31");
    expect(form.get("estimasi_nilai")).toBe("1500000");
    expect(form.get("dq_number")).toBe("DQ-2025-001");
    expect(JSON.parse(form.get("qualification_answers") as string)).toEqual({
      budget_mrr: 50,
      budget_status: "Sudah disetujui",
      pic_name: "Budi",
      pic_email: null,
      need_description: "Migrasi data warehouse",
      need_note: null,
      timeline_date: null,
    });
    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual(["mom.pdf", "rfp.pdf"]);
    expect(form.getAll("file_types")).toEqual(["MoM", "RFP"]);
    expect(captured.headers?.Authorization).toBe("Bearer access-Sales");
    // multipart: Content-Type tidak boleh diset manual agar browser menambahkan boundary
    expect(captured.headers).not.toHaveProperty("Content-Type");
  });

  it("tanpa DQ Number dan tanpa file: field opsional tidak dikirim", async () => {
    useSchema();
    const captured = capturePost(() => created());
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    await screen.findByText("Hasil Scoring BANT");
    expect(captured.form!.has("dq_number")).toBe(false);
    expect(captured.form!.getAll("files")).toHaveLength(0);
  });

  it("menampilkan 'Mengirim request...' dan menonaktifkan tombol selama pengiriman", async () => {
    useSchema();
    let selesai!: () => void;
    const tunggu = new Promise<void>((r) => (selesai = r));
    server.use(http.post(api("/projects"), async () => { await tunggu; return created(); }));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    const tombol = await screen.findByRole("button", { name: "Mengirim request..." });
    expect(tombol).toBeDisabled();
    expect(screen.getByRole("button", { name: "Kembali" })).toBeDisabled();
    expect(screen.getByLabelText(/Anggaran bulanan/)).toBeDisabled();
    selesai();
    await screen.findByText("Hasil Scoring BANT");
  });

  it("skor lolos (>= 60): menampilkan hasil BANT, sub-skor, status, feedback, dan tombol ke detail", async () => {
    useSchema();
    capturePost(() =>
      created({ status: "Pending Assignment", bant_score: 72, sub_scores: { budget: 20, authority: 18, need: 17, timeline: 17 }, scoring_triggered: false, feedback: "Bagus sekali" }),
    );
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));

    expect(await screen.findByText("Hasil Scoring BANT")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Proyek Contoh" })).toBeInTheDocument();
    expect(screen.getByText("Lolos Threshold — Masuk Antrian Assignment")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("Pending Assignment")).toBeInTheDocument();
    expect(screen.getByText("Bagus sekali")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Proyek masuk antrian assignment");
    await user.click(screen.getByRole("button", { name: "Lihat Detail Proyek" }));
    expect(router.push).toHaveBeenCalledWith("/projects/11111111-1111-4111-8111-111111111111");
  });

  it("skor di bawah 60: menampilkan 'Perlu Klarifikasi Tambahan' tanpa feedback bila kosong", async () => {
    useSchema();
    capturePost(() =>
      created({ status: "Need Clarification", bant_score: 40, sub_scores: { budget: 10, authority: 10, need: 10, timeline: 10 }, scoring_triggered: false }),
    );
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByText("Perlu Klarifikasi Tambahan")).toBeInTheDocument();
    expect(screen.getByText("Need Clarification")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Perlu klarifikasi tambahan");
  });

  it("skor tersedia tetapi tanpa rincian sub-skor, status Pending Assignment: toast sukses, form tetap tampil", async () => {
    useSchema();
    capturePost(() => created({ status: "Pending Assignment", bant_score: 65, sub_scores: null, scoring_triggered: false }));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("BANT Score: 65 — Proyek masuk antrian assignment!");
    expect(screen.queryByText("Hasil Scoring BANT")).not.toBeInTheDocument();
  });

  it("skor tanpa rincian sub-skor, status lain: toast error perlu klarifikasi", async () => {
    useSchema();
    capturePost(() => created({ status: "Need Clarification", bant_score: 30, sub_scores: null, scoring_triggered: false }));
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("BANT Score: 30 — Perlu klarifikasi tambahan.");
  });

  it("dengan file (analisis AI berjalan): toast sukses lalu diarahkan ke detail setelah 2 detik; toast hilang setelah 3 detik", async () => {
    useSchema();
    capturePost(() => created({ scoring_triggered: true, bant_score: null, sub_scores: null, status: "Scoring Pending" }));
    const user = setup({ fake: true });
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    const toast = await screen.findByText("Proyek berhasil dibuat! File sedang diproses untuk scoring.");
    // Jam palsu berjalan juga mengikuti waktu nyata (shouldAdvanceTime) → pakai margin, bukan batas tepat.
    expect(router.push).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(router.push).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1500)); // total ~2.5 dtk: redirect (2 dtk) sudah, toast (3 dtk) belum
    expect(router.push).toHaveBeenCalledWith("/projects/11111111-1111-4111-8111-111111111111");
    expect(toast).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.queryByText(/Proyek berhasil dibuat/)).not.toBeInTheDocument();
  });

  it("422 pada field header: kembali ke langkah 1 dengan pesan di field terkait", async () => {
    useSchema();
    capturePost(() =>
      HttpResponse.json(
        { status: "error", message: "Validasi gagal", data: [{ field: "dq_number", reason: "DQ Number sudah dipakai" }, { field: "project_name", reason: "Nama proyek sudah ada" }] },
        { status: 422 },
      ),
    );
    const user = setup();
    await isiLangkah1(user, { dq: "DQ-2025-001" });
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByText("DQ Number sudah dipakai")).toBeInTheDocument();
    expect(screen.getByText("Nama proyek sudah ada")).toBeInTheDocument();
    expect(screen.getByText(/Langkah 1 dari 2/)).toBeInTheDocument();
    expect(screen.getByText("Gagal submit:")).toBeInTheDocument();
    expect(screen.getByLabelText(/DQ Number/)).toHaveAttribute("aria-invalid", "true");
  });

  it("422 pada jawaban kuesioner: tetap di langkah 2 dengan pesan di field terkait", async () => {
    useSchema();
    capturePost(() =>
      HttpResponse.json(
        { status: "error", message: "Validasi gagal", data: [{ field: "qualification_answers.pic_email", reason: "Email tidak valid menurut server" }, { field: "tidak_dikenal", reason: "diabaikan" }] },
        { status: 422 },
      ),
    );
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByText("Email tidak valid menurut server")).toBeInTheDocument();
    expect(screen.getByLabelText(/Email PIC/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Langkah 2 dari 2/)).toBeInTheDocument();
    expect(screen.queryByText("diabaikan")).not.toBeInTheDocument();
    // toast error + tombol aktif kembali
    expect(screen.getByRole("button", { name: "Submit Request" })).toBeEnabled();
  });

  it("error server tanpa rincian field: menampilkan pesan umum dan toast error yang hilang setelah 5 detik", async () => {
    useSchema();
    capturePost(() => HttpResponse.json(errorEnvelope("Server sedang bermasalah"), { status: 500 }));
    const user = setup({ fake: true });
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    const alert = await screen.findByText("Gagal submit:");
    expect(within(alert.parentElement as HTMLElement).getByText("Server sedang bermasalah")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Server sedang bermasalah");
    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1500));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(/Langkah 2 dari 2/)).toBeInTheDocument();
  });

  it("error jaringan: pesan gagal ditampilkan dan pengguna dapat mencoba lagi", async () => {
    useSchema();
    capturePost(() => HttpResponse.error());
    const user = setup();
    await isiLangkah1(user);
    await lanjut(user);
    await isiKuesioner(user);
    await user.click(screen.getByRole("button", { name: "Submit Request" }));
    expect(await screen.findByText("Gagal submit:")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit Request" })).toBeEnabled();
  });
});
