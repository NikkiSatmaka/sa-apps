"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { fetcher, apiRequest } from "@/lib/fetcher";

/**
 * Komponen Calendar Sync — tampilan kalender bulanan Google Calendar
 *
 * Alur:
 * 1. Sync Calendar → fetch events (7 hari lalu + 7 hari depan) via OAuth token
 * 2. Event ditandai sebagai titik pada grid kalender bulanan
 * 3. Klik tanggal → panel detail menampilkan event pada hari itu
 * 4. Klik "Map ke Subtask" pada event → modal pilih proyek + subtask + durasi
 * 5. Submit → POST /calendar/map membuat ActivityLog
 *
 * Requirements: 13.1, 13.2
 */

// Kategori subtask — harus selaras dengan VALID_SUBTASK_CATEGORIES di backend
// Sub-kategori per work_type — selaras dengan backend schemas/activity_log.py
const PROJECT_SUBTASK_CATEGORIES = [
  "Assessment",
  "Internal Meeting",
  "Customer Meeting",
  "Principal Meeting",
  "Commercial Document",
  "Technical Document",
  "Document Review",
] as const;

const NON_PROJECT_SUBTASK_CATEGORIES = [
  "Training",
  "Self-Lab",
  "Self-Learning",
  "Exam",
  "Internal Meeting",
  "Internal Presentation",
  "External Presentation",
  "Principal Meeting",
] as const;

const PROJECT_PHASES = [
  "Pre-Implementation",
  "Implementation",
  "Post-Implementation",
] as const;

type WorkType = "Project" | "Non-Project";
type ProjectPhase = (typeof PROJECT_PHASES)[number];

/** Default fase dari status proyek — selaras backend default_phase_for_status */
function defaultPhaseForStatus(status?: string): ProjectPhase {
  return status === "Handed Over" ? "Implementation" : "Pre-Implementation";
}

const WEEKDAY_LABELS = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
const MONTH_LABELS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

// Konstanta Google Calendar API — fetch langsung dari browser.
// Dilakukan di sisi klien (bukan via backend /calendar/sync) untuk menghindari
// WAF Cloudflare yang memblokir POST ke origin dengan payload token.
// Token Google (OAuth) dikirim langsung browser -> Google via HTTPS.
const GCAL_EVENTS_ENDPOINT =
  "https://www.googleapis.com/calendar/v3/calendars/primary/events";
const GCAL_RANGE_DAYS = 7;
const GCAL_MAX_RESULTS = 200;

/** Bentuk mentah item event dari Google Calendar API */
interface GCalRawEvent {
  id?: string;
  summary?: string;
  description?: string;
  start?: { date?: string; dateTime?: string };
  end?: { date?: string; dateTime?: string };
}

/**
 * Parse satu item event Google menjadi CalendarEvent.
 * Mereplikasi logika backend: deteksi all-day via 'date' vs 'dateTime'.
 */
function parseGCalEvent(item: GCalRawEvent): CalendarEvent | null {
  if (!item.id) return null;
  const startRaw = item.start || {};
  const endRaw = item.end || {};
  const isAllDay = !!startRaw.date && !startRaw.dateTime;
  return {
    gcal_event_id: item.id,
    title: item.summary || "(No Title)",
    description: item.description,
    start: isAllDay ? startRaw.date! : startRaw.dateTime || "",
    end: isAllDay ? endRaw.date || "" : endRaw.dateTime || "",
    is_all_day: isAllDay,
  };
}

interface Project {
  id: string;
  project_name: string;
  status?: string;
}

interface CalendarEvent {
  // Backend mengirim gcal_event_id (bukan id), lihat CalendarEventResponse
  gcal_event_id: string;
  title: string;
  description?: string;
  start: string;
  end: string;
  is_all_day: boolean;
  is_mapped?: boolean;
}

interface CalendarSyncProps {
  /** Daftar proyek untuk mapping */
  projects: Project[];
}

interface MapFormState {
  work_type: WorkType;
  project_id: string;
  project_phase: ProjectPhase;
  subtask_category: string;
  duration_hours: string;
  raw_notes: string;
}

/** Kunci tanggal lokal (YYYY-MM-DD) dari string ISO atau tanggal all-day */
function dateKey(iso: string): string {
  // All-day event: start berupa "YYYY-MM-DD" tanpa waktu
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Kunci tanggal lokal dari objek Date */
function keyFromDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function CalendarSync({ projects }: CalendarSyncProps) {
  const [isSyncing, setIsSyncing] = useState(false);
  const [hasSynced, setHasSynced] = useState(false);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [mappedIds, setMappedIds] = useState<Set<string>>(new Set());

  // Navigasi kalender
  const today = useMemo(() => new Date(), []);
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth()); // 0-11
  const [selectedKey, setSelectedKey] = useState<string>(keyFromDate(today));

  // Mapping modal
  const [mappingEventId, setMappingEventId] = useState<string | null>(null);
  const [mapForm, setMapForm] = useState<MapFormState>({
    work_type: "Project",
    project_id: "",
    project_phase: "Pre-Implementation",
    subtask_category: "",
    duration_hours: "1",
    raw_notes: "",
  });
  const [isMapping, setIsMapping] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  }, []);

  /**
   * Baca #gcal_token / #gcal_error dari URL hash setelah redirect OAuth.
   */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash;
    if (!hash) return;

    const tokenMatch = hash.match(/gcal_token=([^&]+)/);
    const errorMatch = hash.match(/gcal_error=([^&]+)/);

    if (tokenMatch) {
      localStorage.setItem("google_calendar_token", decodeURIComponent(tokenMatch[1]));
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      showToast("success", "Google Calendar terhubung. Klik Sync Calendar untuk memuat event.");
    } else if (errorMatch) {
      localStorage.removeItem("google_calendar_token");
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      showToast("error", "Otorisasi Google Calendar gagal. Silakan coba lagi.");
    }
  }, [showToast]);

  /**
   * Redirect ke Google OAuth untuk mendapatkan Calendar access token.
   */
  const redirectToGoogleAuth = useCallback(async () => {
    try {
      const result = await fetcher<{ auth_url: string }>("/calendar/auth-url");
      window.location.href = result.auth_url;
    } catch {
      showToast("error", "Gagal memulai otorisasi Google Calendar");
    }
  }, [showToast]);

  /**
   * Sync calendar — fetch events LANGSUNG dari Google Calendar API di browser.
   * Tidak lagi via backend /calendar/sync agar tidak kena WAF Cloudflare.
   * Jika token belum ada, redirect ke Google OAuth dulu.
   */
  const handleSync = useCallback(async () => {
    const gcalToken = localStorage.getItem("google_calendar_token");

    if (!gcalToken) {
      showToast("success", "Mengarahkan ke Google untuk otorisasi Calendar...");
      await redirectToGoogleAuth();
      return;
    }

    setIsSyncing(true);
    try {
      // Rentang: 7 hari lalu sampai 7 hari depan
      const now = new Date();
      const timeMin = new Date(now.getTime() - GCAL_RANGE_DAYS * 86400000).toISOString();
      const timeMax = new Date(now.getTime() + GCAL_RANGE_DAYS * 86400000).toISOString();
      const query = new URLSearchParams({
        timeMin,
        timeMax,
        maxResults: String(GCAL_MAX_RESULTS),
        singleEvents: "true",
        orderBy: "startTime",
      });

      const resp = await fetch(`${GCAL_EVENTS_ENDPOINT}?${query.toString()}`, {
        headers: {
          Authorization: `Bearer ${gcalToken}`,
          Accept: "application/json",
        },
      });

      // Token kedaluwarsa / tidak sah → minta re-auth
      if (resp.status === 401 || resp.status === 403) {
        localStorage.removeItem("google_calendar_token");
        showToast("error", "Token Google Calendar kedaluwarsa. Silakan sync ulang untuk otorisasi.");
        return;
      }
      if (!resp.ok) {
        showToast("error", `Gagal sync calendar (Google ${resp.status}).`);
        return;
      }

      const data = await resp.json();
      const items: GCalRawEvent[] = Array.isArray(data?.items) ? data.items : [];
      const fetched = items
        .map(parseGCalEvent)
        .filter((e): e is CalendarEvent => e !== null);

      setEvents(fetched);
      setHasSynced(true);
      showToast(
        "success",
        fetched.length > 0
          ? `Calendar tersinkronisasi — ${fetched.length} event ditemukan`
          : "Calendar tersinkronisasi, tidak ada event pada rentang 7 hari ini"
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Gagal sync calendar";
      showToast("error", message);
    } finally {
      setIsSyncing(false);
    }
  }, [showToast, redirectToGoogleAuth]);

  /** Kelompokkan event per tanggal (key YYYY-MM-DD) */
  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const ev of events) {
      const key = dateKey(ev.start);
      if (!key) continue;
      const list = map.get(key) ?? [];
      list.push(ev);
      map.set(key, list);
    }
    return map;
  }, [events]);

  /** Event untuk tanggal yang dipilih, urut berdasarkan waktu mulai */
  const selectedEvents = useMemo(() => {
    const list = eventsByDate.get(selectedKey) ?? [];
    return [...list].sort((a, b) => a.start.localeCompare(b.start));
  }, [eventsByDate, selectedKey]);

  /** Susun sel-sel grid kalender untuk bulan yang sedang ditampilkan */
  const calendarCells = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1);
    const startWeekday = firstDay.getDay(); // 0 (Min) - 6 (Sab)
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

    const cells: { date: Date | null; key: string }[] = [];
    // Padding awal untuk hari sebelum tanggal 1
    for (let i = 0; i < startWeekday; i++) {
      cells.push({ date: null, key: `pad-start-${i}` });
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const date = new Date(viewYear, viewMonth, d);
      cells.push({ date, key: keyFromDate(date) });
    }
    // Padding akhir agar grid genap (kelipatan 7)
    while (cells.length % 7 !== 0) {
      cells.push({ date: null, key: `pad-end-${cells.length}` });
    }
    return cells;
  }, [viewYear, viewMonth]);

  const goToPrevMonth = () => {
    setViewMonth((m) => {
      if (m === 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  };

  const goToNextMonth = () => {
    setViewMonth((m) => {
      if (m === 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  };

  const goToToday = () => {
    setViewYear(today.getFullYear());
    setViewMonth(today.getMonth());
    setSelectedKey(keyFromDate(today));
  };

  const todayKey = keyFromDate(today);

  /** Buka modal mapping untuk event tertentu */
  const openMappingModal = (eventId: string) => {
    const event = events.find((e) => e.gcal_event_id === eventId);
    setMappingEventId(eventId);
    setMapForm({
      work_type: "Project",
      project_id: "",
      project_phase: "Pre-Implementation",
      subtask_category: "",
      duration_hours: event ? calculateDuration(event.start, event.end, event.is_all_day) : "1",
      raw_notes: event?.description || "",
    });
  };

  /** Hitung durasi (jam) dari start-end, kelipatan 0.25 */
  const calculateDuration = (start: string, end: string, isAllDay: boolean): string => {
    if (isAllDay) return "8";
    const diff = (new Date(end).getTime() - new Date(start).getTime()) / (1000 * 60 * 60);
    return diff > 0 ? Math.round(diff * 4) / 4 + "" : "1";
  };

  /** Submit mapping — POST /calendar/map */
  const handleMap = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const isProject = mapForm.work_type === "Project";
      if (!mappingEventId || !mapForm.subtask_category || (isProject && !mapForm.project_id)) {
        showToast("error", isProject ? "Proyek dan subtask wajib dipilih" : "Subtask wajib dipilih");
        return;
      }

      const event = events.find((ev) => ev.gcal_event_id === mappingEventId);
      if (!event) return;

      setIsMapping(true);
      try {
        const body: Record<string, unknown> = {
          gcal_event_id: mappingEventId,
          work_type: mapForm.work_type,
          subtask_category: mapForm.subtask_category,
          duration_hours: parseFloat(mapForm.duration_hours) || undefined,
          raw_notes: mapForm.raw_notes.trim() || undefined,
          event_title: event.title,
          event_description: event.description || undefined,
          is_all_day: event.is_all_day,
          event_start: event.start,
          event_end: event.end,
        };
        if (isProject) {
          body.project_id = mapForm.project_id;
          body.project_phase = mapForm.project_phase;
        }

        await apiRequest("/calendar/map", {
          method: "POST",
          body,
        });

        setMappedIds((prev) => new Set(prev).add(mappingEventId));
        setMappingEventId(null);
        showToast("success", "Event berhasil di-mapping ke subtask proyek");
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Gagal mapping event";
        showToast("error", message);
      } finally {
        setIsMapping(false);
      }
    },
    [mappingEventId, mapForm, events, showToast]
  );

  /** Format jam event (HH:mm) atau "Seharian" */
  const formatEventTime = (event: CalendarEvent): string => {
    if (event.is_all_day) return "Seharian";
    const start = new Date(event.start);
    const end = new Date(event.end);
    const fmt = (d: Date) =>
      d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
    return `${fmt(start)} – ${fmt(end)}`;
  };

  /** Label tanggal panel detail */
  const selectedDateLabel = useMemo(() => {
    const [y, m, d] = selectedKey.split("-").map(Number);
    if (!y) return "";
    const date = new Date(y, m - 1, d);
    return date.toLocaleDateString("id-ID", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  }, [selectedKey]);

  const mappingEvent = events.find((e) => e.gcal_event_id === mappingEventId);

  return (
    <div className="space-y-4">
      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium ${
            toast.type === "success"
              ? "bg-green-50 text-green-800 border border-green-200"
              : "bg-red-50 text-red-800 border border-red-200"
          }`}
          role="alert"
        >
          {toast.message}
        </div>
      )}

      {/* Header: judul + tombol Sync */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-neutral-700">Google Calendar Events</h3>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="px-4 py-2 text-sm font-medium rounded-lg min-h-[44px]
            bg-primary-600 text-white hover:bg-primary-700
            disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isSyncing ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Syncing...
            </span>
          ) : (
            "Sync Calendar"
          )}
        </button>
      </div>

      {/* Grid kalender + panel detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Kalender bulanan */}
        <div className="lg:col-span-2 rounded-xl border border-neutral-200 p-4">
          {/* Navigasi bulan */}
          <div className="flex items-center justify-between mb-4">
            <h4 className="text-base font-semibold text-neutral-800">
              {MONTH_LABELS[viewMonth]} {viewYear}
            </h4>
            <div className="flex items-center gap-1">
              <button
                onClick={goToPrevMonth}
                className="w-9 h-9 flex items-center justify-center rounded-md hover:bg-neutral-100 text-neutral-600"
                aria-label="Bulan sebelumnya"
              >
                ‹
              </button>
              <button
                onClick={goToToday}
                className="px-3 h-9 text-xs font-medium rounded-md hover:bg-neutral-100 text-primary-600"
              >
                Hari Ini
              </button>
              <button
                onClick={goToNextMonth}
                className="w-9 h-9 flex items-center justify-center rounded-md hover:bg-neutral-100 text-neutral-600"
                aria-label="Bulan berikutnya"
              >
                ›
              </button>
            </div>
          </div>

          {/* Label hari */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {WEEKDAY_LABELS.map((w) => (
              <div key={w} className="text-center text-[11px] font-medium text-neutral-400 py-1">
                {w}
              </div>
            ))}
          </div>

          {/* Sel tanggal */}
          <div className="grid grid-cols-7 gap-1">
            {calendarCells.map((cell) => {
              if (!cell.date) {
                return <div key={cell.key} className="aspect-square" />;
              }
              const dayEvents = eventsByDate.get(cell.key) ?? [];
              const isSelected = cell.key === selectedKey;
              const isToday = cell.key === todayKey;
              return (
                <button
                  key={cell.key}
                  onClick={() => setSelectedKey(cell.key)}
                  className={`aspect-square rounded-md flex flex-col items-center justify-center gap-1
                    text-sm transition-colors relative
                    ${isSelected
                      ? "bg-primary-600 text-white"
                      : isToday
                        ? "bg-primary-50 text-primary-700 hover:bg-primary-100"
                        : "text-neutral-700 hover:bg-neutral-100"
                    }`}
                >
                  <span className={isToday && !isSelected ? "font-semibold" : ""}>
                    {cell.date.getDate()}
                  </span>
                  {/* Penanda event */}
                  {dayEvents.length > 0 && (
                    <span className="flex items-center gap-0.5">
                      {dayEvents.slice(0, 3).map((_, i) => (
                        <span
                          key={i}
                          className={`w-1.5 h-1.5 rounded-full ${
                            isSelected ? "bg-white" : "bg-primary-500"
                          }`}
                        />
                      ))}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {!hasSynced && (
            <p className="mt-4 text-center text-xs text-neutral-400">
              Klik &quot;Sync Calendar&quot; untuk memuat event dari Google Calendar
              (rentang 7 hari lalu sampai 7 hari depan).
            </p>
          )}
        </div>

        {/* Panel detail harian */}
        <div className="rounded-xl border border-neutral-200 p-4">
          <p className="text-[11px] font-medium text-neutral-400 uppercase tracking-wide">
            Detail untuk
          </p>
          <h4 className="text-sm font-semibold text-neutral-800 mb-3">
            {selectedDateLabel}
          </h4>

          {selectedEvents.length === 0 ? (
            <div className="py-8 text-center text-sm text-neutral-400">
              {hasSynced
                ? "Tidak ada event pada tanggal ini"
                : "Belum ada event. Sinkronkan calendar terlebih dahulu."}
            </div>
          ) : (
            <div className="space-y-2">
              {selectedEvents.map((event) => {
                const isMapped = mappedIds.has(event.gcal_event_id) || event.is_mapped;
                return (
                  <div
                    key={event.gcal_event_id}
                    className={`p-3 border rounded-lg ${
                      isMapped ? "border-green-200 bg-green-50" : "border-neutral-200"
                    }`}
                  >
                    <div className="flex items-start gap-2 mb-1">
                      <h5 className="text-sm font-medium text-neutral-800 flex-1 min-w-0 break-words">
                        {event.title}
                      </h5>
                      {event.is_all_day && (
                        <span className="shrink-0 px-1.5 py-0.5 text-[10px] font-medium bg-neutral-100 text-neutral-600 rounded">
                          All Day
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-neutral-500">{formatEventTime(event)}</p>
                    {event.description && (
                      <p className="text-xs text-neutral-400 mt-1 line-clamp-2">
                        {event.description}
                      </p>
                    )}

                    {isMapped ? (
                      <span className="inline-flex items-center gap-1 mt-2 px-2 py-1 text-[11px] font-medium bg-green-100 text-green-700 rounded">
                        ✓ Sudah di-mapping
                      </span>
                    ) : (
                      <button
                        onClick={() => openMappingModal(event.gcal_event_id)}
                        className="mt-2 w-full px-3 py-2 text-xs font-medium rounded-md min-h-[40px]
                          bg-primary-50 text-primary-700 hover:bg-primary-100 transition-colors"
                      >
                        Map ke Subtask
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Modal Mapping */}
      {mappingEventId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold text-neutral-800 mb-1">Map Event ke Subtask</h3>
            <p className="text-sm text-neutral-500 mb-4">{mappingEvent?.title}</p>

            <form onSubmit={handleMap} className="space-y-4">
              {/* Jenis aktivitas (work_type) */}
              <div>
                <label className="block text-sm font-medium text-neutral-700 mb-1">
                  Jenis Aktivitas <span className="text-red-500">*</span>
                </label>
                <div className="flex gap-2">
                  {(["Project", "Non-Project"] as WorkType[]).map((wt) => (
                    <button
                      key={wt}
                      type="button"
                      onClick={() =>
                        setMapForm((f) => ({
                          ...f,
                          work_type: wt,
                          // reset field yang tak relevan + subtask (set berubah)
                          project_id: wt === "Non-Project" ? "" : f.project_id,
                          subtask_category: "",
                        }))
                      }
                      className={`flex-1 px-3 py-2 text-sm font-medium rounded-lg border transition-colors min-h-[40px] ${
                        mapForm.work_type === wt
                          ? "bg-primary-50 text-primary-700 border-primary-300"
                          : "bg-white text-neutral-600 border-neutral-300 hover:bg-neutral-50"
                      }`}
                    >
                      {wt}
                    </button>
                  ))}
                </div>
              </div>

              {/* Proyek + Fase (hanya untuk Project) */}
              {mapForm.work_type === "Project" && (
                <>
                  <div>
                    <label htmlFor="map-project" className="block text-sm font-medium text-neutral-700 mb-1">
                      Proyek <span className="text-red-500">*</span>
                    </label>
                    <select
                      id="map-project"
                      value={mapForm.project_id}
                      onChange={(e) => {
                        const pid = e.target.value;
                        const proj = projects.find((p) => p.id === pid);
                        setMapForm((f) => ({
                          ...f,
                          project_id: pid,
                          project_phase: defaultPhaseForStatus(proj?.status),
                        }));
                      }}
                      className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                        focus:outline-none focus:ring-2 focus:ring-primary-500"
                    >
                      <option value="">Pilih proyek...</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>{p.project_name}</option>
                      ))}
                    </select>
                    {projects.length === 0 && (
                      <p className="text-xs text-amber-600 mt-1">
                        Tidak ada proyek tersedia untuk di-mapping.
                      </p>
                    )}
                  </div>

                  <div>
                    <label htmlFor="map-phase" className="block text-sm font-medium text-neutral-700 mb-1">
                      Fase Proyek <span className="text-red-500">*</span>
                    </label>
                    <select
                      id="map-phase"
                      value={mapForm.project_phase}
                      onChange={(e) =>
                        setMapForm((f) => ({ ...f, project_phase: e.target.value as ProjectPhase }))
                      }
                      className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                        focus:outline-none focus:ring-2 focus:ring-primary-500"
                    >
                      {PROJECT_PHASES.map((ph) => (
                        <option key={ph} value={ph}>{ph}</option>
                      ))}
                    </select>
                  </div>
                </>
              )}

              {/* Subtask (tergantung work_type) */}
              <div>
                <label htmlFor="map-category" className="block text-sm font-medium text-neutral-700 mb-1">
                  Subtask <span className="text-red-500">*</span>
                </label>
                <select
                  id="map-category"
                  value={mapForm.subtask_category}
                  onChange={(e) => setMapForm((f) => ({ ...f, subtask_category: e.target.value }))}
                  className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                    focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">Pilih subtask...</option>
                  {(mapForm.work_type === "Non-Project"
                    ? NON_PROJECT_SUBTASK_CATEGORIES
                    : PROJECT_SUBTASK_CATEGORIES
                  ).map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>

              {/* Durasi */}
              <div>
                <label htmlFor="map-duration" className="block text-sm font-medium text-neutral-700 mb-1">
                  Durasi (jam)
                </label>
                <input
                  id="map-duration"
                  type="number"
                  min="0.25"
                  max="24"
                  step="0.25"
                  value={mapForm.duration_hours}
                  onChange={(e) => setMapForm((f) => ({ ...f, duration_hours: e.target.value }))}
                  className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                    focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>

              {/* Catatan */}
              <div>
                <label htmlFor="map-notes" className="block text-sm font-medium text-neutral-700 mb-1">
                  Catatan
                </label>
                <textarea
                  id="map-notes"
                  value={mapForm.raw_notes}
                  onChange={(e) => setMapForm((f) => ({ ...f, raw_notes: e.target.value }))}
                  rows={3}
                  placeholder="Catatan opsional..."
                  className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm resize-none
                    focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>

              {/* Tombol aksi */}
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setMappingEventId(null)}
                  disabled={isMapping}
                  className="flex-1 py-2.5 px-4 rounded-lg font-medium text-neutral-700
                    border border-neutral-300 hover:bg-neutral-50 min-h-[44px]
                    disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={isMapping}
                  className={`flex-1 py-2.5 px-4 rounded-lg font-medium text-white min-h-[44px]
                    transition-all ${
                      isMapping
                        ? "bg-neutral-400 cursor-not-allowed"
                        : "bg-primary-600 hover:bg-primary-700"
                    }`}
                >
                  {isMapping ? (
                    <span className="flex items-center justify-center gap-2">
                      <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Mapping...
                    </span>
                  ) : (
                    "Simpan Mapping"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
