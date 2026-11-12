"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";

/**
 * Komponen Project Story — timeline activity log untuk satu proyek.
 *
 * Fitur:
 * - Filter berdasarkan kategori subtask dan rentang tanggal
 * - Pagination (20 per halaman — batas maksimum backend)
 * - Tampilkan hasil AI polishing (poin diskusi + action item)
 * - Tombol "Polish Ulang" jika ai_polished_notes masih kosong
 *
 * Requirements: 8.1, 8.5
 */

// Sub-kategori Project — selaras dengan backend schemas/activity_log.py
const SUBTASK_CATEGORIES = [
  "Assessment",
  "Internal Meeting",
  "Customer Meeting",
  "Principal Meeting",
  "Commercial Document",
  "Technical Document",
  "Document Review",
] as const;

interface ActionItem {
  description: string;
  pic?: string | null;
}

interface AiPolishedNotes {
  discussion_points: string[];
  action_items: ActionItem[];
}

interface ActivityLogEntry {
  id_log: string;
  project_phase?: string | null;
  subtask_category: string;
  duration_hours: number;
  raw_notes: string;
  ai_polished_notes: AiPolishedNotes | null;
  created_at: string;
}

interface StoryResponse {
  items: ActivityLogEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface ProjectStoryProps {
  /** ID proyek yang ditampilkan story-nya */
  projectId: string;
}

const PAGE_SIZE = 20;

export function ProjectStory({ projectId }: ProjectStoryProps) {
  // Sales PIC boleh membaca Story tetapi tidak boleh menulis (polish ulang = tingkat TULIS)
  const bisaMenulis = useAuthStore((s) => s.user?.role) !== "Sales";
  const [filterCategory, setFilterCategory] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [polishingIds, setPolishingIds] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (filterCategory) params.set("category", filterCategory);
  // Backend menerima datetime ISO; date_to dibuat inklusif sampai akhir hari
  if (dateFrom) params.set("date_from", `${dateFrom}T00:00:00`);
  if (dateTo) params.set("date_to", `${dateTo}T23:59:59`);

  const { data, error, isLoading, mutate } = useSWR<StoryResponse>(
    `/projects/${projectId}/story?${params.toString()}`,
    fetcher
  );

  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  }, []);

  // Polish ulang — POST /activity-logs/{id}/polish
  const handlePolish = useCallback(
    async (logId: string) => {
      setPolishingIds((prev) => new Set(prev).add(logId));
      try {
        await apiRequest(`/activity-logs/${logId}/polish`, { method: "POST" });
        showToast("success", "AI polishing berhasil");
        mutate();
      } catch (err: unknown) {
        showToast("error", err instanceof Error ? err.message : "Gagal melakukan polishing");
      } finally {
        setPolishingIds((prev) => {
          const next = new Set(prev);
          next.delete(logId);
          return next;
        });
      }
    },
    [mutate, showToast]
  );

  const totalPages = data?.total_pages ?? 0;
  const hasFilter = Boolean(filterCategory || dateFrom || dateTo);

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <div className="space-y-4">
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

      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-3 p-3 bg-neutral-50 rounded-lg border border-neutral-200">
        <div className="flex-1 min-w-[150px]">
          <label htmlFor="filter-category" className="block text-xs text-neutral-500 mb-1">
            Kategori
          </label>
          <select
            id="filter-category"
            value={filterCategory}
            onChange={(e) => {
              setFilterCategory(e.target.value);
              setPage(1);
            }}
            className="w-full px-2 py-2 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="">Semua</option>
            {SUBTASK_CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[140px]">
          <label htmlFor="filter-date-from" className="block text-xs text-neutral-500 mb-1">
            Dari
          </label>
          <input
            id="filter-date-from"
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
            className="w-full px-2 py-2 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        <div className="min-w-[140px]">
          <label htmlFor="filter-date-to" className="block text-xs text-neutral-500 mb-1">
            Sampai
          </label>
          <input
            id="filter-date-to"
            type="date"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
            className="w-full px-2 py-2 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        {hasFilter && (
          <button
            type="button"
            onClick={() => {
              setFilterCategory("");
              setDateFrom("");
              setDateTo("");
              setPage(1);
            }}
            className="px-3 py-2 text-sm text-neutral-600 border border-neutral-300 rounded-md
              hover:bg-white transition-colors min-h-[38px]"
          >
            Reset
          </button>
        )}
      </div>

      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse p-4 border border-neutral-200 rounded-lg">
              <div className="h-4 bg-neutral-200 rounded w-1/4 mb-2" />
              <div className="h-3 bg-neutral-200 rounded w-3/4 mb-1" />
              <div className="h-3 bg-neutral-200 rounded w-1/2" />
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          Gagal memuat data: {error.message}
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="p-6 text-center text-neutral-500 border border-neutral-200 rounded-lg">
          <p className="text-sm">
            {hasFilter
              ? "Tidak ada activity log yang cocok dengan filter."
              : "Belum ada activity log untuk proyek ini."}
          </p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="space-y-3">
          {data.items.map((log) => (
            <li
              key={log.id_log}
              className="p-4 bg-white border border-neutral-200 rounded-lg"
            >
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full font-medium">
                  {log.subtask_category}
                </span>
                {log.project_phase && (
                  <span className="px-2 py-0.5 bg-neutral-100 text-neutral-600 text-xs rounded-full">
                    {log.project_phase}
                  </span>
                )}
                <span className="text-xs text-neutral-500">{formatDate(log.created_at)}</span>
                <span className="text-xs text-neutral-400">•</span>
                <span className="text-xs text-neutral-600 font-medium">
                  {log.duration_hours} jam
                </span>
              </div>

              <p className="text-sm text-neutral-700 whitespace-pre-wrap">{log.raw_notes}</p>

              {log.ai_polished_notes ? (
                <div className="mt-3 p-3 bg-blue-50 border border-blue-100 rounded-md text-sm text-neutral-700 space-y-2">
                  {log.ai_polished_notes.discussion_points.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-blue-700 mb-1">Poin Diskusi</p>
                      <ul className="list-disc pl-5 space-y-0.5">
                        {log.ai_polished_notes.discussion_points.map((point, idx) => (
                          <li key={idx}>{point}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {log.ai_polished_notes.action_items.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-amber-700 mb-1">Action Item</p>
                      <ul className="space-y-0.5">
                        {log.ai_polished_notes.action_items.map((item, idx) => (
                          <li key={idx}>
                            ▸ {item.description}
                            {item.pic && <span className="text-neutral-500"> (PIC: {item.pic})</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : bisaMenulis ? (
                <button
                  type="button"
                  onClick={() => handlePolish(log.id_log)}
                  disabled={polishingIds.has(log.id_log)}
                  className="mt-3 text-xs font-medium px-3 py-1.5 rounded-md min-h-[36px]
                    bg-primary-50 text-primary-700 hover:bg-primary-100
                    disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {polishingIds.has(log.id_log) ? "Memproses..." : "Polish Ulang"}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {data && totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-neutral-500">
            Halaman {page} dari {totalPages} ({data.total} item)
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-2 text-sm border border-neutral-300 rounded-md min-h-[44px]
                hover:bg-neutral-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              ← Sebelumnya
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-2 text-sm border border-neutral-300 rounded-md min-h-[44px]
                hover:bg-neutral-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Selanjutnya →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
