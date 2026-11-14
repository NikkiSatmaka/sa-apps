"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "./LoadError";
import { useAuthStore } from "@/store/auth";
import { isPrivileged as isPrivilegedUser } from "@/lib/roles";

/**
 * Section Subtask — work item yang bisa ditugaskan per proyek.
 *
 * Satu permukaan dipakai dua peran (kontrol dimunculkan sesuai role):
 * - SA (pemilik subtask): melihat subtask miliknya sebagai to-do list dengan
 *   satu tombol "Tandai selesai" (`→ done`). Tidak ada tombol "Mulai" manual —
 *   transisi ke `in_progress` terjadi otomatis saat mencatat activity log
 *   terhadap subtask (lihat ADR 0008).
 * - SA yang ditugaskan di project (utama/tambahan, #147): juga boleh menambah subtask; subtask
 *   baru belum punya assignee, Lead_SA/Admin yang menugaskan.
 * - Lead_SA/admin (`is_admin`): melihat seluruh daftar plus kontrol tambah, hapus, dan
 *   assign/reassign subtask ke SA.
 *
 * Badge status per item + ringkasan "N/M selesai" di header dihitung dari data
 * `GET /projects/{id}/subtasks` yang sudah di-fetch (tanpa endpoint agregat).
 *
 * Subtask kaya (#124): tiap item menampilkan due date, penanda "Terlambat" (dihitung server:
 * due_date < hari ini dan belum selesai), deskripsi, dan estimasi jam. Lead_SA/Admin dan SA
 * pemilik boleh mengubah ketiganya (hak sama dengan ubah status). Penolakan server (mis. 409
 * pada proyek Closed/Lost) ditampilkan apa adanya.
 *
 * Endpoint:
 * - GET    /projects/{id}/subtasks
 * - POST   /projects/{id}/subtasks
 * - PATCH  /projects/subtasks/{id} (ubah description, due_date, estimate_hours)
 * - PATCH  /projects/subtasks/{id}/status
 * - PATCH  /projects/subtasks/{id}/assign
 * - GET    /projects/{id}/tim-sa (opsi assignee; penentu SA ditugaskan: SA utama + SA tambahan)
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
  description: string | null;
  due_date: string | null;
  /** Decimal dari backend sebagai string (mis. "12.50"). */
  estimate_hours: string | null;
  terlambat: boolean;
  created_at: string;
  updated_at: string;
}

interface AnggotaTim {
  id: string;
  name: string;
}

interface TimSA {
  sa_utama: AnggotaTim | null;
  sa_tambahan: AnggotaTim[];
}

interface SubtaskSectionProps {
  projectId: string;
}

/** Isian form ketiga field opsional (string mentah dari input). */
interface IsianKaya {
  description: string;
  due_date: string;
  estimate_hours: string;
}

const ISIAN_KOSONG: IsianKaya = { description: "", due_date: "", estimate_hours: "" };

const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

/** "2030-01-15" → "15 Jan 2030" (tanpa Date, jadi bebas pergeseran zona waktu). */
function formatTanggal(iso: string): string {
  const [tahun, bulan, hari] = iso.split("-").map(Number);
  return `${hari} ${BULAN[bulan - 1]} ${tahun}`;
}

/** "12.50" → "12,5 jam". */
function formatJam(desimal: string): string {
  return `${String(Number(desimal)).replace(".", ",")} jam`;
}

/**
 * Ubah isian form menjadi nilai request. Kosong → null (mengosongkan field).
 * Mengembalikan pesan error bila estimasi bukan angka atau negatif.
 */
function bacaIsian(
  isian: IsianKaya
): { error: string } | { description: string | null; due_date: string | null; estimate_hours: string | null } {
  const jam = isian.estimate_hours.trim();
  if (jam !== "") {
    const angka = Number(jam);
    if (Number.isNaN(angka)) return { error: "Estimasi jam harus berupa angka." };
    if (angka < 0) return { error: "Estimasi jam tidak boleh negatif." };
  }
  return {
    description: isian.description.trim() || null,
    due_date: isian.due_date || null,
    estimate_hours: jam || null,
  };
}

/** Tiga input opsional yang dipakai bersama oleh form tambah dan form ubah. */
function FieldKaya({
  idAwalan,
  nilai,
  onChange,
  disabled,
}: {
  idAwalan: string;
  nilai: IsianKaya;
  onChange: (n: IsianKaya) => void;
  disabled?: boolean;
}) {
  const kelasInput =
    "w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none";
  return (
    <>
      <div>
        <label htmlFor={`${idAwalan}-deskripsi`} className="text-xs font-medium text-neutral-600 mb-1 block">
          Deskripsi:
        </label>
        <textarea
          id={`${idAwalan}-deskripsi`}
          value={nilai.description}
          maxLength={2000}
          rows={2}
          disabled={disabled}
          onChange={(e) => onChange({ ...nilai, description: e.target.value })}
          className={kelasInput}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor={`${idAwalan}-due`} className="text-xs font-medium text-neutral-600 mb-1 block">
            Due date:
          </label>
          <input
            id={`${idAwalan}-due`}
            type="date"
            value={nilai.due_date}
            disabled={disabled}
            onChange={(e) => onChange({ ...nilai, due_date: e.target.value })}
            className={kelasInput}
          />
        </div>
        <div>
          <label htmlFor={`${idAwalan}-jam`} className="text-xs font-medium text-neutral-600 mb-1 block">
            Estimasi (jam):
          </label>
          <input
            id={`${idAwalan}-jam`}
            type="number"
            min={0}
            step="0.25"
            value={nilai.estimate_hours}
            disabled={disabled}
            onChange={(e) => onChange({ ...nilai, estimate_hours: e.target.value })}
            className={kelasInput}
          />
        </div>
      </div>
    </>
  );
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
  const [isianBaru, setIsianBaru] = useState<IsianKaya>(ISIAN_KOSONG);
  // id_subtask yang form ubah field-nya terbuka, beserta isiannya.
  const [editId, setEditId] = useState<string | null>(null);
  const [isianEdit, setIsianEdit] = useState<IsianKaya>(ISIAN_KOSONG);
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

  // Tim SA project (ADR 0014): opsi assign untuk privileged, dan penentu "SA ditugaskan" (hak
  // tambah subtask, #147) untuk SA. Sales/Product tidak melihat section ini, jadi tidak di-fetch.
  const { data: tim } = useSWR<TimSA>(
    isPrivileged || isSA ? `/projects/${projectId}/tim-sa` : null,
    fetcher
  );
  // Cermin `TingkatAkses.BUAT_SUBTASK`: SA ditugaskan (utama/tambahan; id DAN peran SA), Lead_SA,
  // Admin. Bukan penentu hak: backend tetap memeriksa.
  const saDitugaskan =
    isSA &&
    !!user?.id &&
    [tim?.sa_utama?.id, ...(tim?.sa_tambahan ?? []).map((s) => s.id)].includes(user.id);
  const bisaTambah = isPrivileged || saDitugaskan;
  const opsiAssign = [
    ...(tim?.sa_utama ? [{ id: tim.sa_utama.id, label: `${tim.sa_utama.name} (SA utama)` }] : []),
    ...(tim?.sa_tambahan ?? []).map((s) => ({ id: s.id, label: `${s.name} (SA tambahan)` })),
  ];

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
    const isian = bacaIsian(isianBaru);
    if ("error" in isian) {
      setError(isian.error);
      return;
    }
    // Field opsional yang kosong tidak dikirim sama sekali.
    const body: Record<string, string> = { title };
    if (isian.description) body.description = isian.description;
    if (isian.due_date) body.due_date = isian.due_date;
    if (isian.estimate_hours) body.estimate_hours = isian.estimate_hours;
    setIsAdding(true);
    setError(null);
    try {
      await apiRequest(`/projects/${projectId}/subtasks`, {
        method: "POST",
        body,
      });
      setNewTitle("");
      setIsianBaru(ISIAN_KOSONG);
      setShowAddForm(false);
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menambahkan subtask.");
    } finally {
      setIsAdding(false);
    }
  };

  const bukaEdit = (subtask: Subtask) => {
    setError(null);
    if (editId === subtask.id_subtask) {
      setEditId(null);
      return;
    }
    setIsianEdit({
      description: subtask.description ?? "",
      due_date: subtask.due_date ?? "",
      estimate_hours: subtask.estimate_hours ?? "",
    });
    setEditId(subtask.id_subtask);
  };

  const handleSimpanEdit = async (subtask: Subtask) => {
    const isian = bacaIsian(isianEdit);
    if ("error" in isian) {
      setError(isian.error);
      return;
    }
    setBusyId(subtask.id_subtask);
    setError(null);
    try {
      await apiRequest(`/projects/subtasks/${subtask.id_subtask}`, {
        method: "PATCH",
        body: isian,
      });
      setEditId(null);
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menyimpan perubahan subtask.");
    } finally {
      setBusyId(null);
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
              : saDitugaskan
                ? "Tambah work item, atau kerjakan yang ditugaskan kepada Anda."
                : "Work item yang ditugaskan kepada Anda."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {totalCount > 0 && (
            <span className="text-xs font-medium text-neutral-500" aria-label={`${doneCount} dari ${totalCount} subtask selesai`}>
              {doneCount}/{totalCount} selesai
            </span>
          )}
          {bisaTambah && (
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

      {/* Form tambah subtask (SA ditugaskan/Lead_SA/Admin); assignee awal kosong */}
      {bisaTambah && showAddForm && (
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
          <FieldKaya idAwalan="subtask-baru" nilai={isianBaru} onChange={setIsianBaru} disabled={isAdding} />
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
                      {subtask.terlambat && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full border bg-red-100 text-red-700 border-red-200">
                          Terlambat
                        </span>
                      )}
                    </div>
                    {subtask.description && (
                      <p className="text-xs text-neutral-600 mt-1 whitespace-pre-line">{subtask.description}</p>
                    )}
                    {(subtask.due_date || subtask.estimate_hours !== null) && (
                      <p className="text-xs text-neutral-500 mt-1 flex gap-3 flex-wrap">
                        {subtask.due_date && <span>Jatuh tempo: {formatTanggal(subtask.due_date)}</span>}
                        {subtask.estimate_hours !== null && <span>Estimasi: {formatJam(subtask.estimate_hours)}</span>}
                      </p>
                    )}
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

                    {/* Lead_SA/Admin atau SA pemilik: ubah description, due date, estimasi */}
                    {(isPrivileged || (isSA && isOwner)) && (
                      <button
                        type="button"
                        onClick={() => bukaEdit(subtask)}
                        disabled={busy}
                        className="px-3 py-1.5 text-xs font-medium text-neutral-700 border border-neutral-300
                                   rounded-lg hover:bg-neutral-50 transition-colors min-h-[32px]
                                   disabled:opacity-50 disabled:cursor-not-allowed"
                        aria-label={`Ubah subtask ${subtask.title}`}
                        aria-expanded={editId === subtask.id_subtask}
                      >
                        Ubah
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

                {/* Form ubah field (Lead_SA/Admin atau SA pemilik) */}
                {editId === subtask.id_subtask && (
                  <div className="mt-3 pt-3 border-t border-neutral-200 space-y-3">
                    <FieldKaya
                      idAwalan={`ubah-${subtask.id_subtask}`}
                      nilai={isianEdit}
                      onChange={setIsianEdit}
                      disabled={busy}
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => handleSimpanEdit(subtask)}
                        disabled={busy}
                        className="px-3 py-1.5 text-xs font-medium text-white bg-primary-600 rounded-lg
                                   hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busy ? "Menyimpan..." : "Simpan"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditId(null)}
                        disabled={busy}
                        className="px-3 py-1.5 text-xs font-medium text-neutral-700 border border-neutral-300
                                   rounded-lg hover:bg-neutral-50 transition-colors disabled:opacity-50"
                      >
                        Batal ubah
                      </button>
                    </div>
                  </div>
                )}

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
                      {opsiAssign.map((sa) => (
                        <option key={sa.id} value={sa.id}>
                          {sa.label}
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
