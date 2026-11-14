import { act, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, stubLocation, successEnvelope } from "@/test";
import { GCAL_EVENTS_URL } from "@/test/msw/handlers/operations";
import { CalendarSync } from "./CalendarSync";

const projects = [
  { id: "p-1", project_name: "Migrasi Cloud", status: "Intake" },
  { id: "p-2", project_name: "Rollout Jaringan", status: "Handed Over" },
];

// Hari "ini" tetap: Sabtu, 15 Maret 2025 (waktu lokal) agar grid/rentang deterministik.
const NOW = new Date(2025, 2, 15, 10, 0, 0);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
});

function setup(props: Partial<React.ComponentProps<typeof CalendarSync>> = {}) {
  return renderWithProviders(<CalendarSync projects={projects} {...props} />, { role: "SA" });
}

const gcalEvent = (over: Record<string, unknown> = {}) => ({
  id: "ev-1",
  summary: "Rapat Kickoff",
  description: "Bahas ruang lingkup",
  start: { dateTime: "2025-03-15T09:00:00" },
  end: { dateTime: "2025-03-15T10:30:00" },
  ...over,
});

function useGoogleEvents(items: unknown) {
  const captured: { url?: URL; auth?: string | null } = {};
  server.use(
    http.get(GCAL_EVENTS_URL, ({ request }) => {
      captured.url = new URL(request.url);
      captured.auth = request.headers.get("Authorization");
      return HttpResponse.json(items === undefined ? {} : { items });
    })
  );
  return captured;
}

async function syncWithToken(user: ReturnType<typeof setup>["user"], items: unknown) {
  localStorage.setItem("google_calendar_token", "gtoken");
  const captured = useGoogleEvents(items);
  await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
  return captured;
}

const toast = () => screen.findByRole("alert");

describe("CalendarSync — tampilan awal & navigasi bulan", () => {
  it("menampilkan bulan/tahun berjalan, label hari, tanggal terpilih hari ini, dan petunjuk sync", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Maret 2025" })).toBeInTheDocument();
    for (const w of ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"]) expect(screen.getByText(w)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "31" })).toBeInTheDocument(); // Maret 2025 punya 31 hari
    expect(screen.queryByRole("button", { name: "32" })).not.toBeInTheDocument();
    expect(screen.getByText(/Sabtu, 15 Maret 2025/)).toBeInTheDocument();
    expect(screen.getByText(/Klik "Sync Calendar" untuk memuat event/)).toBeInTheDocument();
    expect(screen.getByText("Belum ada event. Sinkronkan calendar terlebih dahulu.")).toBeInTheDocument();
  });

  it("navigasi bulan sebelumnya/berikutnya, lintas tahun, dan kembali dengan 'Hari Ini'", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Bulan sebelumnya" }));
    expect(screen.getByRole("heading", { name: "Februari 2025" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bulan sebelumnya" }));
    await user.click(screen.getByRole("button", { name: "Bulan sebelumnya" }));
    expect(screen.getByRole("heading", { name: "Desember 2024" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hari Ini" }));
    expect(screen.getByRole("heading", { name: "Maret 2025" })).toBeInTheDocument();

    for (let i = 0; i < 10; i++) await user.click(screen.getByRole("button", { name: "Bulan berikutnya" }));
    expect(screen.getByRole("heading", { name: "Januari 2026" })).toBeInTheDocument();
  });

  it("memilih tanggal lain mengubah label panel detail dan 'Hari Ini' mengembalikannya", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "20" }));
    expect(screen.getByText(/Kamis, 20 Maret 2025/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hari Ini" }));
    expect(screen.getByText(/Sabtu, 15 Maret 2025/)).toBeInTheDocument();
  });
});

describe("CalendarSync — sync Google Calendar", () => {
  it("tanpa token: mengambil auth-url lalu mengarahkan browser ke Google", async () => {
    const loc = stubLocation("http://localhost/activity-logs/calendar");
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    await waitFor(() => expect(loc.href).toBe("https://accounts.google.com/o/oauth2/auth?x=1"));
    expect(screen.getByRole("alert")).toHaveTextContent("Mengarahkan ke Google untuk otorisasi Calendar...");
  });

  it("tanpa token dan auth-url gagal: toast error", async () => {
    server.use(http.get(api("/calendar/auth-url"), () => HttpResponse.json(errorEnvelope("x"), { status: 500 })));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Gagal memulai otorisasi Google Calendar"));
  });

  it("dengan token: memanggil Google dengan bearer + rentang ±7 hari dan menampilkan event pada hari terpilih", async () => {
    const { user } = setup();
    const captured = await syncWithToken(user, [gcalEvent()]);

    expect(await toast()).toHaveTextContent("Calendar tersinkronisasi — 1 event ditemukan");
    expect(captured.auth).toBe("Bearer gtoken");
    const q = captured.url!.searchParams;
    expect(q.get("timeMin")).toBe(new Date(NOW.getTime() - 7 * 86400000).toISOString());
    expect(q.get("timeMax")).toBe(new Date(NOW.getTime() + 7 * 86400000).toISOString());
    expect(q.get("maxResults")).toBe("200");
    expect(q.get("singleEvents")).toBe("true");
    expect(q.get("orderBy")).toBe("startTime");

    expect(screen.getByRole("heading", { name: "Rapat Kickoff", level: 5 })).toBeInTheDocument();
    expect(screen.getByText(/09[.:]00 – 10[.:]30/)).toBeInTheDocument();
    expect(screen.getByText("Bahas ruang lingkup")).toBeInTheDocument();
    expect(screen.queryByText(/Klik "Sync Calendar" untuk memuat event/)).not.toBeInTheDocument();
  });

  it("menandai tanggal yang punya event dengan titik (maks 3) dan menampilkan event saat tanggal dipilih", async () => {
    const { user } = setup();
    await syncWithToken(user, [
      gcalEvent({ id: "a", summary: "A", start: { dateTime: "2025-03-18T08:00:00" }, end: { dateTime: "2025-03-18T09:00:00" } }),
      gcalEvent({ id: "b", summary: "B", start: { dateTime: "2025-03-18T10:00:00" }, end: { dateTime: "2025-03-18T11:00:00" } }),
      gcalEvent({ id: "c", summary: "C", start: { dateTime: "2025-03-18T12:00:00" }, end: { dateTime: "2025-03-18T13:00:00" } }),
      gcalEvent({ id: "d", summary: "D", start: { dateTime: "2025-03-18T14:00:00" }, end: { dateTime: "2025-03-18T15:00:00" } }),
    ]);
    await toast();
    const day18 = screen.getByRole("button", { name: "18" });
    expect(day18.querySelectorAll("span > span")).toHaveLength(3);
    expect(screen.getByText("Tidak ada event pada tanggal ini")).toBeInTheDocument();

    await user.click(day18);
    expect(screen.getAllByRole("heading", { level: 5 }).map((h) => h.textContent)).toEqual(["A", "B", "C", "D"]);
  });

  it("event seharian: lencana All Day dan label 'Seharian'; event tanpa judul memakai '(No Title)'", async () => {
    const { user } = setup();
    await syncWithToken(user, [
      { id: "ad", summary: "Libur", start: { date: "2025-03-15" }, end: { date: "2025-03-16" } },
      { id: "nt", start: { dateTime: "2025-03-15T13:00:00" }, end: { dateTime: "2025-03-15T14:00:00" } },
    ]);
    await toast();
    expect(screen.getByText("All Day")).toBeInTheDocument();
    expect(screen.getByText("Seharian")).toBeInTheDocument();
    expect(screen.getByText("(No Title)")).toBeInTheDocument();
  });

  it("event tanpa id atau tanpa tanggal valid dilewati", async () => {
    const { user } = setup();
    await syncWithToken(user, [
      { summary: "Tanpa ID", start: { dateTime: "2025-03-15T09:00:00" }, end: { dateTime: "2025-03-15T10:00:00" } },
      { id: "x", summary: "Tanggal rusak", start: {}, end: {} },
      gcalEvent({ id: "ok", summary: "Valid" }),
    ]);
    expect(await toast()).toHaveTextContent("2 event ditemukan"); // "Tanggal rusak" terhitung event tapi tidak ditampilkan
    expect(screen.getByText("Valid")).toBeInTheDocument();
    expect(screen.queryByText("Tanpa ID")).not.toBeInTheDocument();
    expect(screen.queryByText("Tanggal rusak")).not.toBeInTheDocument();
  });

  it("tidak ada event: pesan khusus dan keadaan kosong 'Tidak ada event pada tanggal ini'", async () => {
    const { user } = setup();
    await syncWithToken(user, []);
    expect(await toast()).toHaveTextContent("Calendar tersinkronisasi, tidak ada event pada rentang 7 hari ini");
    expect(screen.getByText("Tidak ada event pada tanggal ini")).toBeInTheDocument();
  });

  it("respons tanpa array items diperlakukan sebagai kosong", async () => {
    const { user } = setup();
    await syncWithToken(user, undefined);
    expect(await toast()).toHaveTextContent("tidak ada event");
  });

  it.each([401, 403])("Google %i: token dihapus dan pengguna diminta sync ulang", async (status) => {
    localStorage.setItem("google_calendar_token", "kedaluwarsa");
    server.use(http.get(GCAL_EVENTS_URL, () => new HttpResponse(null, { status })));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    expect(await toast()).toHaveTextContent("Token Google Calendar kedaluwarsa. Silakan sync ulang untuk otorisasi.");
    expect(localStorage.getItem("google_calendar_token")).toBeNull();
  });

  it("Google 500: toast berisi status, token dipertahankan", async () => {
    localStorage.setItem("google_calendar_token", "gtoken");
    server.use(http.get(GCAL_EVENTS_URL, () => new HttpResponse(null, { status: 500 })));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    expect(await toast()).toHaveTextContent("Gagal sync calendar (Google 500).");
    expect(localStorage.getItem("google_calendar_token")).toBe("gtoken");
    expect(screen.getByRole("button", { name: "Sync Calendar" })).toBeEnabled();
  });

  it("kegagalan jaringan menampilkan pesan error", async () => {
    localStorage.setItem("google_calendar_token", "gtoken");
    server.use(http.get(GCAL_EVENTS_URL, () => HttpResponse.error()));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    expect(await toast()).toHaveTextContent(/Failed to fetch|fetch failed|Network/i);
  });

  it("menampilkan 'Syncing...' dan menonaktifkan tombol selama request", async () => {
    localStorage.setItem("google_calendar_token", "gtoken");
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.get(GCAL_EVENTS_URL, async () => { await gate; return HttpResponse.json({ items: [] }); }));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
    expect(await screen.findByRole("button", { name: /Syncing/ })).toBeDisabled();
    release();
    await toast();
    expect(screen.getByRole("button", { name: "Sync Calendar" })).toBeEnabled();
  });
});

describe("CalendarSync — callback OAuth lewat URL hash", () => {
  it("menukar gcal_code lewat POST; token Google tidak perlu ada di redirect", async () => {
    server.use(
      http.post(api("/auth/calendar/exchange"), () =>
        HttpResponse.json({ access_token: "ya29.exchange" }),
      ),
    );
    stubLocation("http://localhost/activity-logs/calendar?x=1#gcal_code=once-code");
    const replace = vi.spyOn(window.history, "replaceState");
    setup();
    expect(await toast()).toHaveTextContent("Google Calendar terhubung. Klik Sync Calendar untuk memuat event.");
    expect(localStorage.getItem("google_calendar_token")).toBe("ya29.exchange");
    expect(replace).toHaveBeenCalledWith(null, "", "/activity-logs/calendar?x=1");
  });

  it("legacy #gcal_token dibersihkan tetapi tidak dipercaya", async () => {
    localStorage.setItem("google_calendar_token", "lama");
    stubLocation("http://localhost/activity-logs/calendar?x=1#gcal_token=ya29.abc%2Fdef");
    const replace = vi.spyOn(window.history, "replaceState");
    setup();
    expect(await toast()).toHaveTextContent("Otorisasi Google Calendar perlu diulang.");
    expect(localStorage.getItem("google_calendar_token")).toBeNull();
    expect(replace).toHaveBeenCalledWith(null, "", "/activity-logs/calendar?x=1");
  });

  it("#gcal_error menghapus token lama dan menampilkan toast error", async () => {
    localStorage.setItem("google_calendar_token", "lama");
    stubLocation("http://localhost/activity-logs/calendar#gcal_error=access_denied");
    const replace = vi.spyOn(window.history, "replaceState");
    setup();
    expect(await toast()).toHaveTextContent("Otorisasi Google Calendar gagal. Silakan coba lagi.");
    expect(localStorage.getItem("google_calendar_token")).toBeNull();
    expect(replace).toHaveBeenCalled();
  });

  it("hash lain diabaikan", () => {
    stubLocation("http://localhost/activity-logs/calendar#section");
    setup();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(localStorage.getItem("google_calendar_token")).toBeNull();
  });
});

describe("CalendarSync — mapping event ke subtask", () => {
  async function openMapping(items: unknown[] = [gcalEvent()], projectList = projects) {
    const utils = setup({ projects: projectList });
    await syncWithToken(utils.user, items);
    await toast();
    await utils.user.click(screen.getByRole("button", { name: "Map ke Subtask" }));
    return { ...utils, modal: screen.getByRole("heading", { name: "Map Event ke Subtask" }).parentElement as HTMLElement };
  }

  function captureMap() {
    const c: { body?: Record<string, unknown>; auth?: string | null } = {};
    server.use(
      http.post(api("/calendar/map"), async ({ request }) => {
        c.body = (await request.json()) as Record<string, unknown>;
        c.auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope({}), { status: 201 });
      })
    );
    return c;
  }

  it("modal terisi dari event: judul, durasi dihitung (1.5), catatan dari deskripsi", async () => {
    await openMapping();
    expect(screen.getByText("Rapat Kickoff", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByLabelText("Durasi (jam)")).toHaveValue(1.5);
    expect(screen.getByLabelText("Catatan")).toHaveValue("Bahas ruang lingkup");
    expect(screen.getByLabelText(/^Fase Proyek/)).toHaveValue("Pre-Implementation");
  });

  it("durasi: event seharian = 8 jam; selisih tidak positif = 1 jam; dibulatkan ke 0.25", async () => {
    const first = await openMapping([{ id: "ad", summary: "Libur", start: { date: "2025-03-15" }, end: { date: "2025-03-16" } }]);
    expect(screen.getByLabelText("Durasi (jam)")).toHaveValue(8);
    first.unmount();

    const second = await openMapping([gcalEvent({ end: { dateTime: "2025-03-15T08:00:00" } })]);
    expect(screen.getByLabelText("Durasi (jam)")).toHaveValue(1);
    second.unmount();

    await openMapping([gcalEvent({ end: { dateTime: "2025-03-15T09:20:00" } })]);
    expect(screen.getByLabelText("Durasi (jam)")).toHaveValue(0.25 * Math.round((20 / 60) * 4));
  });

  it("proyek tanpa daftar: peringatan 'Tidak ada proyek tersedia'", async () => {
    await openMapping([gcalEvent()], []);
    expect(screen.getByText("Tidak ada proyek tersedia untuk di-mapping.")).toBeInTheDocument();
  });

  it("memilih proyek menyesuaikan fase dari status; fase bisa diubah manual", async () => {
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-2");
    expect(screen.getByLabelText(/^Fase Proyek/)).toHaveValue("Implementation");
    await user.selectOptions(screen.getByLabelText(/^Fase Proyek/), "Post-Implementation");
    expect(screen.getByLabelText(/^Fase Proyek/)).toHaveValue("Post-Implementation");
  });

  it("validasi Project: proyek dan subtask wajib → toast error tanpa request", async () => {
    const hit = vi.fn();
    server.use(http.post(api("/calendar/map"), () => { hit(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = await openMapping();
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    expect(await screen.findByText("Proyek dan subtask wajib dipilih")).toBeInTheDocument();
    expect(hit).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Map Event ke Subtask" })).toBeInTheDocument();
  });

  it("validasi Non-Project: subtask wajib; daftar subtask berganti dan proyek disembunyikan", async () => {
    const { user } = await openMapping();
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    expect(screen.queryByLabelText(/^Proyek/)).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Training" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Assessment" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    expect(await screen.findByText("Subtask wajib dipilih")).toBeInTheDocument();
  });

  it("berpindah Non-Project → Project mengosongkan subtask dan menampilkan lagi proyek", async () => {
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Assessment");
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    await user.click(screen.getByRole("button", { name: "Project" }));
    expect(screen.getByLabelText(/^Proyek/)).toHaveValue(""); // project_id direset saat melewati Non-Project
    expect(screen.getByLabelText(/^Subtask/)).toHaveValue("");
  });

  it("sukses (Project): body lengkap, modal menutup, event ditandai sudah di-mapping, toast sukses", async () => {
    const c = captureMap();
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Customer Meeting");
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));

    expect(await screen.findByText("Event berhasil di-mapping ke subtask proyek")).toBeInTheDocument();
    expect(c.body).toEqual({
      gcal_event_id: "ev-1",
      work_type: "Project",
      subtask_category: "Customer Meeting",
      duration_hours: 1.5,
      raw_notes: "Bahas ruang lingkup",
      event_title: "Rapat Kickoff",
      event_description: "Bahas ruang lingkup",
      is_all_day: false,
      event_start: "2025-03-15T09:00:00",
      event_end: "2025-03-15T10:30:00",
      project_id: "p-1",
      project_phase: "Pre-Implementation",
    });
    expect(c.auth).toBe("Bearer access-SA");
    expect(screen.queryByRole("heading", { name: "Map Event ke Subtask" })).not.toBeInTheDocument();
    expect(screen.getByText("✓ Sudah di-mapping")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Map ke Subtask" })).not.toBeInTheDocument();
  });

  it("sukses (Non-Project): tanpa project_id/project_phase; catatan/durasi kosong menjadi undefined", async () => {
    const c = captureMap();
    const { user } = await openMapping([gcalEvent({ description: undefined })]);
    await user.click(screen.getByRole("button", { name: "Non-Project" }));
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Training");
    await user.clear(screen.getByLabelText("Durasi (jam)"));
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    await screen.findByText("Event berhasil di-mapping ke subtask proyek");
    expect(c.body).not.toHaveProperty("project_id");
    expect(c.body).not.toHaveProperty("project_phase");
    expect(c.body).toMatchObject({ work_type: "Non-Project", subtask_category: "Training" });
    expect(c.body!.duration_hours).toBeUndefined();
    expect(c.body!.raw_notes).toBeUndefined();
    expect(c.body!.event_description).toBeUndefined();
  });

  it("catatan yang diubah dikirim ter-trim", async () => {
    const c = captureMap();
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Assessment");
    await user.clear(screen.getByLabelText("Catatan"));
    await user.type(screen.getByLabelText("Catatan"), "  baru  ");
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    await screen.findByText("Event berhasil di-mapping ke subtask proyek");
    expect(c.body!.raw_notes).toBe("baru");
  });

  it("menampilkan 'Mapping...' selama request", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/calendar/map"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Assessment");
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    expect(await screen.findByRole("button", { name: /Mapping\.\.\./ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
    release();
    await screen.findByText("✓ Sudah di-mapping");
  });

  it("error server: toast error, modal tetap terbuka, event belum ditandai", async () => {
    server.use(http.post(api("/calendar/map"), () => HttpResponse.json(errorEnvelope("Event sudah pernah di-mapping"), { status: 409 })));
    const { user } = await openMapping();
    await user.selectOptions(screen.getByLabelText(/^Proyek/), "p-1");
    await user.selectOptions(screen.getByLabelText(/^Subtask/), "Assessment");
    await user.click(screen.getByRole("button", { name: "Simpan Mapping" }));
    expect(await screen.findByText("Event sudah pernah di-mapping")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Map Event ke Subtask" })).toBeInTheDocument();
    expect(screen.queryByText("✓ Sudah di-mapping")).not.toBeInTheDocument();
  });

  it("Batal menutup modal tanpa request", async () => {
    const { user } = await openMapping();
    await user.click(within(screen.getByRole("heading", { name: "Map Event ke Subtask" }).parentElement!).getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("heading", { name: "Map Event ke Subtask" })).not.toBeInTheDocument();
  });
});

describe("CalendarSync — toast", () => {
  it("toast hilang otomatis setelah 3 detik", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW });
    stubLocation("http://localhost/x#gcal_token=t");
    setup();
    expect(await toast()).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
