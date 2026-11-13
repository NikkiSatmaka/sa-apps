"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "./LoadError";
import { useAuthStore } from "@/store/auth";
import type { AvailableSA } from "@/lib/api/assignment";
import { isPrivileged as isPrivilegedUser } from "@/lib/roles";

/**
 * Section Subtask — work item yang bisa ditugaskan per proyek.
 *
 * Satu permukaan dipakai dua peran (kontrol dimunculkan sesuai role):
 * - SA (pemilik subtask): melihat subtask miliknya sebagai to-do list dengan
 *   satu tombol "Tandai selesai" (`→ done`). Tidak ada tombol "Mulai" manual —
 *   transisi ke `in_progress` terjadi otomatis saat mencatat activity log
 *   terhadap subtask (lihat ADR 0008).
 * - Lead_SA/admin (`is_admin`): melihat seluruh daftar plus kontrol tambah, hapus, dan
 *   assign/reassign subtask ke SA.
 *
 * Badge status per item + ringkasan "N/M selesai" di header dihitung dari data
 * `GET /projects/{id}/subtasks` yang sudah di-fetch (tanpa endpoint agregat).
 *
 * Endpoint yang direuse (tidak ada endpoint baru):
 * - GET    /projects/{id}/subtasks
 * - POST   /projects/{id}/subtasks
 * - PATCH  /projects/subtasks/{id}/status
 * - PATCH  /projects/subtasks/{id}/assign
 * - DELETE /projects/subtasks/{id}
 */

type SubtaskStatus = "open" | "in_progress" | "done";

interface Subtask {
  id_subtask: string;
  id_project: string;
  title: string;
  status: SubtaskStatus;
  assigned_sa: string | null;
  assigned_sa_name: string | null;
  created_at: string;
  updated_at: string;
}

interface SubtaskSectionProps {
  projectId: string;
}

/** Badge visual per status subtask. */
function statusBadge(status: SubtaskStatus): { label: string; className: string } {
  switch (status) {
    case "done":
      return { label: "Selesai", className: "bg-green-100 text-green-700 border-green-200" };
    case "in_progress":
      return { label: "Dikerjakan", className: "bg-blue-100 text-blue-700 border-blue-200" };
    case "open":
    default:
      return { label: "Terbuka", className: "bg-neutral-100 text-neutral-600 border-neutral-200" };
  }
}

export function SubtaskSection({ projectId }: SubtaskSectionProps) {
  const { user } = useAuthStore();

  const isPrivileged = isPrivilegedUser(user);
  const isSA = user?.role === "SA";

  const [newTitle, setNewTitle] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // id_subtask yang sedang diproses (status/assign/delete) — untuk disable tombol.
  const [busyId, setBusyId] = useState<string | null>(null);
  // id_subtask yang panel assign-nya terbuka (Lead_SA/Admin).
  const [assignOpenId, setAssignOpenId] = useState<string | null>(null);

  const { data, mutate, isLoading, error: loadError } = useSWR<{ items: Subtask[]; total: number }>(
    `/projects/${projectId}/subtasks`,
    fetcher
  );

  // Daftar SA untuk kontrol assign — hanya di-fetch untuk role privileged.
  const { data: saList } = useSWR<AvailableSA[]>(
    isPrivileged ? "/sa/available" : null,
    fetcher
  );

  // Gagal memuat (dan belum ada data lama): tampilkan error, bukan keadaan kosong.
  const gagalMemuat = Boolean(loadError) && !data;

  const allSubtasks = data?.items ?? [];

  // SA melihat to-do list miliknya; Lead_SA/Admin melihat seluruh daftar.
  const visibleSubtasks = isPrivileged
    ? allSubtasks
    : allSubtasks.filter((s) => s.assigned_sa === user?.id);

  // Ringkasan "N/M selesai" adalah glance progres PROYEK (spec #58 user story 7):
  // selalu dihitung dari seluruh subtask proyek untuk kedua role, bukan hanya
  // subtask milik SA. Daftar yang ditampilkan ke SA tetap terfilter (to-do list).
  const totalCount = allSubtasks.length;
  const doneCount = allSubtasks.filter((s) => s.status === "done").length;

  const handleAdd = async () => {
    const title = newTitle.trim();
    if (!title) return;
    setIsAdding(true);
    setError(null);
    try {
      await apiRequest(`/projects/${projectId}/subtasks`, {
        method: "POST",
        body: { title },
      });
      setNewTitle("");
      setShowAddForm(false);
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menambahkan subtask.");
    } finally {
      setIsAdding(false);
    }
  };

  const handleMarkDone = async (subtask: Subtask) => {
    setBusyId(subtask.id_subtask);
    setError(null);
    try {
      await apiRequest(`/projects/subtasks/${subtask.id_subtask}/status`, {
        method: "PATCH",
        body: { status: "done" },
      });
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menandai subtask selesai.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (subtask: Subtask) => {
    if (!confirm(`Hapus subtask "${subtask.title}"?`)) return;
    setBusyId(subtask.id_subtask);
    setError(null);
    try {
      await apiRequest(`/projects/subtasks/${subtask.id_subtask}`, {
        method: "DELETE",
      });
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menghapus subtask.");
    } finally {
      setBusyId(null);
    }
  };

  const handleAssign = async (subtask: Subtask, assignedSa: string | null) => {
    setBusyId(subtask.id_subtask);
    setError(null);
    try {
      await apiRequest(`/projects/subtasks/${subtask.id_subtask}/assign`, {
        method: "PATCH",
        body: { assigned_sa: assignedSa },
      });
      setAssignOpenId(null);
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memperbarui penugasan subtask.");
    } finally {
      setBusyId(null);
    }
  };

  // Jangan render apa pun untuk role yang tidak relevan (mis. Sales).
  if (!isPrivileged && !isSA) {
    return null;
  }

  return (
    <section className="bg-white border border-neutral-200 rounded-lg p-5" aria-labelledby="subtask-heading">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 id="subtask-heading" className="text-sm font-semibold text-neutral-700">
            Subtask
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            {isPrivileged
              ? "Work item teknis proyek — tambah, tugaskan, atau hapus."
              : "Work item yang ditugaskan kepada Anda."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {totalCount > 0 && (
            <span className="text-xs font-medium text-neutral-500" aria-label={`${doneCount} dari ${totalCount} subtask selesai`}>
              {doneCount}/{totalCount} selesai
            </span>
          )}
          {isPrivileged && (
            <button
              type="button"
              onClick={() => {
                setShowAddForm((v) => !v);
                setError(null);
              }}
              className="px-3 py-1.5 text-xs font-medium text-primary-600 border border-primary-200
                         rounded-lg hover:bg-primary-50 transition-colors min-h-[32px]"
              aria-expanded={showAddForm}
            >
              {showAddForm ? "Batal" : "+ Tambah"}
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Form tambah subtask (Lead_SA/Admin) */}
      {isPrivileged && showAddForm && (
        <div className="mb-4 p-3 bg-neutral-50 rounded-lg border border-neutral-200 space-y-3">
          <div>
            <label htmlFor="subtask-title" className="text-xs font-medium text-neutral-600 mb-1 block">
              Judul subtask:
            </label>
            <input
              id="subtask-title"
              type="text"
              value={newTitle}
              maxLength={150}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTitle.trim()) handleAdd();
              }}
              placeholder="mis. Peer Review HLD"
              className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                         focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
            />
          </div>
          <button
            type="button"
            onClick={handleAdd}
            disabled={!newTitle.trim() || isAdding}
            className="w-full px-3 py-2 text-sm font-medium text-white bg-primary-600
                       rounded-lg hover:bg-primary-700 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAdding ? "Menambahkan..." : "Tambah Subtask"}
          </button>
        </div>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="space-y-2 animate-pulse" aria-hidden="true">
          <div className="h-12 bg-neutral-100 rounded-lg" />
          <div className="h-12 bg-neutral-100 rounded-lg" />
        </div>
      )}

      {/* Gagal memuat: jangan tampilkan keadaan kosong yang menyesatkan */}
      {gagalMemuat && (
        <LoadError message="Gagal memuat daftar subtask." onRetry={() => mutate()} />
      )}

      {/* Daftar subtask */}
      {!isLoading && !gagalMemuat && visibleSubtasks.length === 0 ? (
        <p className="text-sm text-neutral-500 text-center py-3">
          {isPrivileged
            ? "Belum ada subtask di proyek ini."
            : "Belum ada subtask yang ditugaskan kepada Anda."}
        </p>
      ) : (
        <ul className="space-y-2">
          {visibleSubtasks.map((subtask) => {
            const badge = statusBadge(subtask.status);
            const busy = busyId === subtask.id_subtask;
            const isOwner = subtask.assigned_sa === user?.id;
            return (
              <li
                key={subtask.id_subtask}
                className="p-3 bg-neutral-50 rounded-lg border border-neutral-100"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={`px-2 py-0.5 text-xs font-medium rounded-full border ${badge.className}`}
                      >
                        {badge.label}
                      </span>
                      <p className="text-sm font-medium text-neutral-800 truncate">
                        {subtask.title}
                      </p>
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">
                      Ditugaskan ke:{" "}
                      <span className="font-medium text-neutral-600">
                        {subtask.assigned_sa_name ?? "Belum ditugaskan"}
                      </span>
                    </p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {/* SA pemilik: satu tombol "Tandai selesai" (→ done) */}
                    {isSA && isOwner && subtask.status !== "done" && (
                      <button
                        type="button"
                        onClick={() => handleMarkDone(subtask)}
                        disabled={busy}
                        className="px-3 py-1.5 text-xs font-medium text-green-700 border border-green-300
                                   rounded-lg hover:bg-green-50 transition-colors min-h-[32px]
                                   disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busy ? "Menyimpan..." : "Tandai selesai"}
                      </button>
                    )}

                    {/* Lead_SA/Admin: assign/reassign + hapus */}
                    {isPrivileged && (
                      <>
                        <button
                          type="button"
                          onClick={() =>
                            setAssignOpenId((cur) =>
                              cur === subtask.id_subtask ? null : subtask.id_subtask
                            )
                          }
                          disabled={busy}
                          className="px-3 py-1.5 text-xs font-medium text-neutral-700 border border-neutral-300
                                     rounded-lg hover:bg-neutral-50 transition-colors min-h-[32px]
                                     disabled:opacity-50 disabled:cursor-not-allowed"
                          aria-expanded={assignOpenId === subtask.id_subtask}
                        >
                          Tugaskan
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(subtask)}
                          disabled={busy}
                          className="p-1.5 text-neutral-400 hover:text-red-600 transition-colors
                                     disabled:opacity-50 disabled:cursor-not-allowed"
                          aria-label={`Hapus subtask ${subtask.title}`}
                          title="Hapus subtask"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Panel assign/reassign (Lead_SA/Admin) */}
                {isPrivileged && assignOpenId === subtask.id_subtask && (
                  <div className="mt-3 pt-3 border-t border-neutral-200">
                    <label
                      htmlFor={`assign-${subtask.id_subtask}`}
                      className="text-xs font-medium text-neutral-600 mb-1 block"
                    >
                      Tugaskan ke SA:
                    </label>
                    <select
                      id={`assign-${subtask.id_subtask}`}
                      value={subtask.assigned_sa ?? ""}
                      disabled={busy}
                      onChange={(e) => handleAssign(subtask, e.target.value || null)}
                      className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                                 focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none
                                 disabled:opacity-50"
                    >
                      <option value="">— Lepas penugasan —</option>
                      {(saList ?? []).map((sa) => (
                        <option key={sa.id} value={sa.id}>
                          {sa.name} ({sa.active_project_count} proyek)
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
