"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

/**
 * Modal Blocking — Instruksi HLD setelah Won
 *
 * Modal non-dismissable yang ditampilkan saat proyek berubah status ke "Won".
 * SA harus meng-acknowledge dengan klik tombol "Buat HLD" yang akan
 * mengarahkan ke halaman pembuatan dokumen.
 *
 * Modal ini:
 * - Tidak bisa ditutup dengan klik backdrop
 * - Tidak bisa ditutup dengan tombol Escape
 * - Tidak memiliki tombol close (X)
 * - Hanya bisa di-dismiss melalui tombol "Buat HLD"
 *
 * Requirements: 17.1
 */

interface HandoverModalProps {
  /** ID proyek yang baru Won */
  projectId: string;
  /** Nama proyek untuk ditampilkan di modal */
  projectName: string;
  /** Callback setelah user klik "Buat HLD" */
  onAcknowledge?: () => void;
}

export function HandoverModal({
  projectId,
  projectName,
  onAcknowledge,
}: HandoverModalProps) {
  const router = useRouter();

  /**
   * Handle klik tombol "Buat HLD"
   * Navigasi ke halaman dokumen proyek untuk membuat HLD
   */
  const handleCreateHLD = useCallback(() => {
    // Panggil callback jika ada (misal untuk update state parent)
    onAcknowledge?.();

    // Navigasi ke halaman dokumen proyek
    router.push(`/projects/${projectId}/documents`);
  }, [projectId, router, onAcknowledge]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="handover-modal-title"
      aria-describedby="handover-modal-desc"
    >
      {/* Backdrop non-dismissable — tidak ada onClick handler */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        aria-hidden="true"
      />

      {/* Modal content */}
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
        {/* Ikon informasi */}
        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 rounded-full bg-primary-100 flex items-center justify-center">
            <svg
              className="w-7 h-7 text-primary-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </div>
        </div>

        {/* Judul */}
        <h2
          id="handover-modal-title"
          className="text-lg font-bold text-neutral-900 text-center"
        >
          Proyek Won!
        </h2>

        {/* Nama proyek */}
        <p className="text-sm text-neutral-600 text-center mt-1">
          {projectName}
        </p>

        {/* Instruksi */}
        <div id="handover-modal-desc" className="mt-5 space-y-3">
          <p className="text-sm text-neutral-700 text-center">
            Selamat! Proyek ini sudah Won. Langkah selanjutnya adalah 
            membuat dokumen <strong>High Level Design (HLD)</strong> untuk 
            proses handover ke tim PMO dan Delivery.
          </p>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
            <p className="text-xs text-amber-800">
              <strong>Penting:</strong> Handover otomatis akan dimulai setelah 
              HLD berstatus &quot;Final&quot;. Pastikan HLD sudah lengkap dan 
              di-review sebelum difinalkan.
            </p>
          </div>
        </div>

        {/* Tombol aksi — satu-satunya cara dismiss modal */}
        <button
          onClick={handleCreateHLD}
          className="w-full mt-6 py-3 px-4 rounded-lg font-semibold text-white 
                     bg-primary-600 hover:bg-primary-700 active:bg-primary-800
                     transition-colors duration-100 min-h-[44px]
                     focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          autoFocus
        >
          Buat HLD
        </button>
      </div>
    </div>
  );
}
