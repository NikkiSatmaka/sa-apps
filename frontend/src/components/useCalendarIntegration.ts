"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, type ApiErrorResponse, fetcher, apiRequest } from "@/lib/fetcher";
import type { IntegrationOperationResponse } from "@/lib/api/projects";


export interface CalendarEvent {
  gcal_event_id: string;
  title: string;
  description?: string;
  start: string;
  end: string;
  is_all_day: boolean;
}

export type CalendarToast = (type: "success" | "error", message: string) => void;

type WorkType = "Project" | "Non-Project";
type ProjectPhase = "Pre-Implementation" | "Implementation" | "Post-Implementation";

export interface MapFormState {
  work_type: WorkType;
  project_id: string;
  project_phase: ProjectPhase;
  subtask_category: string;
  duration_hours: string;
  raw_notes: string;
}

interface CalendarSyncErrorData {
  integration_operation: IntegrationOperationResponse | null;
}

interface CalendarSyncResponse {
  events: Array<{
    gcal_event_id: string;
    title: string;
    description: string | null;
    start: string | null;
    end: string | null;
    duration_hours: number;
    is_all_day: boolean;
  }>;
  total_events: number;
  integration_operation: IntegrationOperationResponse | null;
}

const INITIAL_MAP_FORM: MapFormState = {
  work_type: "Project",
  project_id: "",
  project_phase: "Pre-Implementation",
  subtask_category: "",
  duration_hours: "1",
  raw_notes: "",
};

function calculateDuration(start: string, end: string, isAllDay: boolean): string {
  if (isAllDay) return "8";
  const diff = (new Date(end).getTime() - new Date(start).getTime()) / (1000 * 60 * 60);
  return diff > 0 ? Math.round(diff * 4) / 4 + "" : "1";
}

/** Owns Calendar OAuth, synchronization, and mapping state and API operations. */
export function useCalendarIntegration(showToast: CalendarToast) {
  const [isSyncing, setIsSyncing] = useState(false);
  const [hasSynced, setHasSynced] = useState(false);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [mappedIds, setMappedIds] = useState<Set<string>>(new Set());
  const [mappingEventId, setMappingEventId] = useState<string | null>(null);
  const [mapForm, setMapForm] = useState<MapFormState>(INITIAL_MAP_FORM);
  const [isMapping, setIsMapping] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.removeItem("google_calendar_token");
    const hash = window.location.hash;
    if (!hash) return;

    const params = new URLSearchParams(hash.slice(1));
    const code = params.get("gcal_code");
    const error = params.get("gcal_error");
    const legacyToken = params.has("gcal_token");
    if (!code && !error && !legacyToken) return;

    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    if (legacyToken && !code && !error) {
      showToast("error", "Otorisasi Google Calendar perlu diulang.");
      return;
    }
    if (error) {
      showToast("error", "Otorisasi Google Calendar gagal. Silakan coba lagi.");
      return;
    }

    void apiRequest<{ connected: boolean }>("/auth/calendar/exchange", {
      body: { code },
    }).then(() => {
      showToast("success", "Google Calendar terhubung. Klik Sync Calendar untuk memuat event.");
    }).catch(() => {
      showToast("error", "Otorisasi Google Calendar gagal. Silakan coba lagi.");
    });
  }, [showToast]);

  const redirectToGoogleAuth = useCallback(async () => {
    try {
      const result = await fetcher<{ auth_url: string }>("/calendar/auth-url");
      window.location.href = result.auth_url;
    } catch {
      showToast("error", "Gagal memulai otorisasi Google Calendar");
    }
  }, [showToast]);

  const handleSync = useCallback(async () => {
    setIsSyncing(true);
    try {
      const result = await apiRequest<CalendarSyncResponse>("/calendar/sync", { body: {} });
      const fetched = (Array.isArray(result?.events) ? result.events : []).map((event) => ({
        ...event,
        description: event.description ?? undefined,
        start: event.start ?? "",
        end: event.end ?? "",
      }));

      setEvents(fetched);
      setHasSynced(true);
      showToast(
        "success",
        fetched.length > 0
          ? `Calendar tersinkronisasi — ${fetched.length} event ditemukan`
          : "Calendar tersinkronisasi, tidak ada event pada rentang 7 hari ini"
      );
    } catch (err: unknown) {
      const calendarError = err instanceof ApiError
        ? err.response as ApiErrorResponse<CalendarSyncErrorData> | null
        : null;
      if (err instanceof ApiError && err.status === 401) {
        if ((calendarError?.message ?? err.message).toLowerCase().includes("calendar session not found")) {
          showToast("success", "Mengarahkan ke Google untuk otorisasi Calendar...");
          await redirectToGoogleAuth();
        } else {
          showToast("error", "Token Google Calendar kedaluwarsa. Silakan sync ulang untuk otorisasi.");
        }
        return;
      }

      const message = calendarError?.message ?? (err instanceof Error ? err.message : "Gagal sync calendar");
      const googleStatus = message.match(/Google Calendar API error \((\d{3})\)/)?.[1];
      if (googleStatus === "401" || googleStatus === "403") {
        showToast("error", "Token Google Calendar kedaluwarsa. Silakan sync ulang untuk otorisasi.");
      } else if (googleStatus) {
        showToast("error", `Gagal sync calendar (Google ${googleStatus}).`);
      } else {
        showToast("error", message);
      }
    } finally {
      setIsSyncing(false);
    }
  }, [showToast, redirectToGoogleAuth]);

  const openMappingModal = useCallback((eventId: string) => {
    const event = events.find((item) => item.gcal_event_id === eventId);
    setMappingEventId(eventId);
    setMapForm({
      ...INITIAL_MAP_FORM,
      duration_hours: event ? calculateDuration(event.start, event.end, event.is_all_day) : "1",
      raw_notes: event?.description || "",
    });
  }, [events]);

  const handleMap = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const isProject = mapForm.work_type === "Project";
    if (!mappingEventId || !mapForm.subtask_category || (isProject && !mapForm.project_id)) {
      showToast("error", isProject ? "Proyek dan subtask wajib dipilih" : "Subtask wajib dipilih");
      return;
    }

    const event = events.find((item) => item.gcal_event_id === mappingEventId);
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

      await apiRequest("/calendar/map", { method: "POST", body });
      setMappedIds((previous) => new Set(previous).add(mappingEventId));
      setMappingEventId(null);
      showToast("success", "Event berhasil di-mapping ke subtask proyek");
    } catch (err: unknown) {
      showToast("error", err instanceof Error ? err.message : "Gagal mapping event");
    } finally {
      setIsMapping(false);
    }
  }, [events, mapForm, mappingEventId, showToast]);

  return {
    events,
    hasSynced,
    handleMap,
    handleSync,
    isMapping,
    isSyncing,
    mapForm,
    mappedIds,
    mappingEventId,
    openMappingModal,
    setMapForm,
    setMappingEventId,
  };
}
