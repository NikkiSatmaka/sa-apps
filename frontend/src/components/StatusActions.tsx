"use client";

import { useState } from "react";
import useSWR from "swr";
import { apiRequest, fetcher } from "@/lib/fetcher";
import { aksiStatusTersedia, type AksiStatus } from "@/lib/status";
import { useAuthStore } from "@/store/auth";
import { useToastStore } from "@/store/toast";

/**
 * Tombol aksi status proyek (spec §2.0 "Siklus status", ADR 0013).
 *
 * Tombol hanya tampil bila peran berhak (aturan di `lib/status.ts`, cermin `workflow.py`).
 * Semua aksi memakai `PATCH /projects/{id}/status` dengan dialog konfirmasi; alasan wajib untuk
 * `Lost` dan buka kembali `Closed`/`Lost` (hanya `is_admin`). Aksi lain punya jalur sendiri dan
 * tidak ada di sini: `Awaiting Assignment` → `Assigned` (assign SA), `Won` → `Handed Over`
 * (handover), `In Progress` otomatis dari backend.
 *
 * Bukan penentu hak: backend tetap menolak (403/400/409) dan pesannya (`message`) ditampilkan.
 */

export interface StatusActionsProject {
  id_project: string;
  status: string;
  previous_status?: string | null;
  lost_reason?: string | null;
  sales_pic?: { id: string | null } | null;
  product_pic?: { id: string | null } | null;
  assigned_sa?: { id: string | null } | null;
}

export interface StatusActionsProps {
  project: StatusActionsProject;
  /** Dipanggil setelah transisi berhasil (muat ulang detail proyek). */
  onChanged: () => void;
}

interface TimSA {
  sa_utama: { id: string } | null;
  sa_tambahan: { id: string }[];
}

const MAKS_ALASAN = 500;

export function StatusActions({ project, onChanged }: StatusActionsProps) {
  const user = useAuthStore((s) => s.user);
  const showToast = useToastStore((s) => s.showToast);

  // SA tambahan punya hak setara SA utama (ADR 0014); detail proyek hanya memuat SA utama.
  const { data: tim } = useSWR<TimSA>(`/projects/${project.id_project}/tim-sa`, fetcher);
  const saIds = [project.assigned_sa?.id, tim?.sa_utama?.id, ...(tim?.sa_tambahan ?? []).map((s) => s.id)];

  const [aktif, setAktif] = useState<AksiStatus | null>(null);
  const [alasan, setAlasan] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sibuk, setSibuk] = useState(false);

  const aksi = aksiStatusTersedia({
    actor: user,
    status: project.status,
    previousStatus: project.previous_status,
    salesPicId: project.sales_pic?.id,
    productPicId: project.product_pic?.id,
    saIds,
  });

  const buka = (a: AksiStatus) => {
    setAktif(a);
    setAlasan("");
    setError(null);
  };
  const tutup = () => setAktif(null);

  const alasanBersih = alasan.trim();
  const bisaKirim = aktif !== null && !sibuk && (!aktif.butuhAlasan || alasanBersih.length > 0);

  const kirim = async () => {
    if (!aktif || !bisaKirim) return;
    setSibuk(true);
    setError(null);
    try {
      await apiRequest(`/projects/${project.id_project}/status`, {
        method: "PATCH",
        body: { new_status: aktif.newStatus, ...(alasanBersih ? { reason: alasanBersih } : {}) },
      });
      showToast("success", `Status proyek diubah ke ${aktif.newStatus}.`);
      setAktif(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengubah status proyek.");
    } finally {
      setSibuk(false);
    }
  };

  const tutupBaca = project.status === "Closed" || project.status === "Lost";

  if (aksi.length === 0 && !tutupBaca && project.status !== "On Hold") return null;

  return (
    <div className="space-y-3">
      {project.status === "Lost" && project.lost_reason && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
          <span className="font-medium">Alasan Lost:</span> {project.lost_reason}
        </p>
      )}
      {tutupBaca && (
        <p className="text-sm text-neutral-600 bg-neutral-50 border border-neutral-200 rounded-lg p-3">
          Proyek {project.status} bersifat read-only. Hanya Admin yang dapat membukanya kembali.
        </p>
      )}
      {project.status === "On Hold" && (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3">
          Proyek dijeda{project.previous_status ? ` (sebelumnya ${project.previous_status})` : ""}. Timer SLA DQ
          berhenti selama On Hold.
        </p>
      )}

      {aksi.length > 0 && (
        <div role="group" aria-label="Aksi status" className="flex flex-wrap gap-2">
          {aksi.map((a) => (
            <button
              key={a.kunci}
              type="button"
              onClick={() => buka(a)}
              className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                         rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px]"
            >
              {a.label}
            </button>
          ))}
        </div>
      )}

      {aktif && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div
            role="dialog"
            aria-modal="true"
            aria-label={aktif.label}
            className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
          >
            <h3 className="text-lg font-semibold text-neutral-900 mb-2">{aktif.label}</h3>
            <p className="text-sm text-neutral-600 mb-3">
              Status proyek akan berubah dari <strong>{project.status}</strong> ke <strong>{aktif.newStatus}</strong>.
            </p>
            <label className="block text-sm text-neutral-700">
              {aktif.butuhAlasan ? "Alasan (wajib)" : "Alasan (opsional)"}
              <textarea
                value={alasan}
                onChange={(e) => setAlasan(e.target.value)}
                maxLength={MAKS_ALASAN}
                rows={3}
                className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
              />
            </label>
            {error && (
              <p role="alert" className="mt-3 text-sm text-red-700">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={tutup}
                disabled={sibuk}
                className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                           rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px] disabled:opacity-50"
              >
                Batal
              </button>
              <button
                type="button"
                onClick={kirim}
                disabled={!bisaKirim}
                className="px-3 py-1.5 text-sm font-medium text-white bg-primary-600 rounded-lg
                           hover:bg-primary-700 transition-colors min-h-[36px] disabled:opacity-50"
              >
                {sibuk ? "Menyimpan..." : "Konfirmasi"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
