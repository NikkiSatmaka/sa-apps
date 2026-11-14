"use client";

import { useState } from "react";
import useSWR from "swr";
import { triggerHandover, type HandoverReadiness } from "@/lib/api/handover";
import { fetcher } from "@/lib/fetcher";
import { bisaHandover } from "@/lib/status";
import { useAuthStore } from "@/store/auth";
import { useToastStore } from "@/store/toast";

/**
 * Tombol "Handover" (`Won` → `Handed Over`, spec §2.0, ADR 0013) di detail proyek.
 *
 * Transisi ini tidak lewat `PATCH /projects/{id}/status` (backend menolaknya); jalurnya
 * `POST /projects/{id}/handover`. Tombol hanya tampil pada `Won` untuk peran yang berhak menurut
 * backend (`TingkatAkses.HANDOVER`, lihat `bisaHandover` di `lib/status.ts`). Dialog memuat
 * kesiapan (`GET /handover-status`), menampilkan `missing_items`, dan menahan submit selama belum
 * `ready`. Error backend (400/403/409) tampil di dialog.
 *
 * Bukan penentu hak: backend tetap menolak, dan pesannya (`message`) ditampilkan.
 */

export interface HandoverActionProject {
  id_project: string;
  project_name: string;
  status: string;
  assigned_sa?: { id: string | null } | null;
}

export interface HandoverActionProps {
  project: HandoverActionProject;
  /** Dipanggil setelah handover berhasil (muat ulang detail proyek). */
  onDone: () => void;
}

interface TimSA {
  sa_utama: { id: string } | null;
  sa_tambahan: { id: string }[];
}

export function HandoverAction({ project, onDone }: HandoverActionProps) {
  const user = useAuthStore((s) => s.user);
  const showToast = useToastStore((s) => s.showToast);

  // SA tambahan punya hak setara SA utama (ADR 0014); detail proyek hanya memuat SA utama.
  const { data: tim } = useSWR<TimSA>(
    project.status === "Won" ? `/projects/${project.id_project}/tim-sa` : null,
    fetcher,
  );
  const saIds = [project.assigned_sa?.id, tim?.sa_utama?.id, ...(tim?.sa_tambahan ?? []).map((s) => s.id)];

  const [terbuka, setTerbuka] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sibuk, setSibuk] = useState(false);

  const { data: kesiapan, error: gagalMuat } = useSWR<HandoverReadiness>(terbuka ? `/projects/${project.id_project}/handover-status` : null, fetcher);

  if (!bisaHandover({ actor: user, status: project.status, saIds })) return null;

  // Hanya data kesiapan yang menentukan; revalidasi key yang sama oleh pelanggan lain (halaman
  // detail) tidak boleh menonaktifkan tombol, karena klik yang jatuh saat itu hilang tanpa jejak.
  const bisaKirim = terbuka && !sibuk && !!kesiapan && kesiapan.ready;

  const buka = () => {
    setError(null);
    setTerbuka(true);
  };

  const kirim = async () => {
    if (!bisaKirim) return;
    setSibuk(true);
    setError(null);
    try {
      await triggerHandover(project.id_project);
      showToast("success", "Handover berhasil. Status proyek diubah ke Handed Over.");
      setTerbuka(false);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memproses handover.");
    } finally {
      setSibuk(false);
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={buka}
        className="px-3 py-1.5 text-sm font-medium text-white bg-primary-600 rounded-lg
                   hover:bg-primary-700 transition-colors min-h-[36px]"
      >
        Handover
      </button>

      {terbuka && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Handover Proyek"
            className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
          >
            <h3 className="text-lg font-semibold text-neutral-900 mb-2">Handover Proyek</h3>
            <p className="text-sm text-neutral-600 mb-3">
              Status <strong>{project.project_name}</strong> akan berubah dari <strong>Won</strong> ke{" "}
              <strong>Handed Over</strong>. PMO dan Delivery akan diberi notifikasi.
            </p>

            {gagalMuat && !kesiapan && (
              <p role="alert" className="text-sm text-red-700 mb-3">
                Gagal memuat kesiapan handover.
              </p>
            )}
            {!kesiapan && !gagalMuat && <p className="text-sm text-neutral-500 mb-3">Memeriksa kesiapan...</p>}

            {kesiapan && (
              <div className="space-y-3 mb-3">
                <dl className="text-sm text-neutral-700 space-y-1">
                  <div className="flex justify-between gap-3">
                    <dt className="text-neutral-500">Email PMO Lead</dt>
                    <dd>{kesiapan.pmo_email ?? "Belum dikonfigurasi"}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-neutral-500">Email Delivery Lead</dt>
                    <dd>{kesiapan.delivery_email ?? "Belum dikonfigurasi"}</dd>
                  </div>
                </dl>
                {!kesiapan.ready && (
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                    <p className="text-sm font-medium text-amber-800">Belum siap di-handover. Lengkapi:</p>
                    <ul className="mt-1 list-disc pl-5 text-sm text-amber-800">
                      {kesiapan.missing_items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {error && (
              <p role="alert" className="mb-3 text-sm text-red-700">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => setTerbuka(false)}
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
                {sibuk ? "Memproses..." : "Konfirmasi Handover"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
