"use client";

/**
 * Komponen indikator offline dan "Menunggu Sinkronisasi" (Requirement 12.5)
 *
 * Menampilkan:
 * - Banner "Anda sedang offline" saat koneksi terputus
 * - Badge "Menunggu Sinkronisasi" dengan jumlah item yang masih akan dikirim
 * - Peringatan untuk item gagal permanen (ditolak server / melewati batas percobaan), dengan
 *   tombol "Buang" — data tidak dibuang diam-diam
 */

import { useEffect, useState } from "react";
import {
  discardFailedItems,
  getFailedItems,
  getPendingItems,
  isOnline,
} from "@/lib/offline-queue";

export function OfflineIndicator() {
  const [online, setOnline] = useState(true);
  const [queueCount, setQueueCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);

  useEffect(() => {
    // Set state awal
    setOnline(isOnline());
    setQueueCount(getPendingItems().length);
    setFailedCount(getFailedItems().length);

    // Listen perubahan koneksi
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);

    // Listen perubahan queue
    const handleQueueUpdate = () => {
      setQueueCount(getPendingItems().length);
      setFailedCount(getFailedItems().length);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    window.addEventListener("offline-queue-updated", handleQueueUpdate);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("offline-queue-updated", handleQueueUpdate);
    };
  }, []);

  return (
    <>
      {/* Banner offline */}
      {!online && (
        <div
          role="status"
          aria-live="polite"
          className="fixed top-0 left-0 right-0 z-50 bg-amber-500 text-white text-center py-2 px-4 text-sm font-medium transition-all duration-200"
        >
          <span className="inline-flex items-center gap-2">
            <svg
              className="w-4 h-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M18.364 5.636a9 9 0 010 12.728M5.636 5.636a9 9 0 000 12.728M12 12h.01"
              />
            </svg>
            Anda sedang offline — perubahan akan disinkronkan saat koneksi kembali
          </span>
        </div>
      )}

      {/* Item gagal permanen: butuh perhatian pengguna */}
      {failedCount > 0 && (
        <div
          role="alert"
          className="fixed bottom-16 left-4 z-40 bg-red-50 border border-red-300 text-red-800 rounded-lg px-3 py-2 text-sm font-medium shadow-md flex items-center gap-3"
        >
          <span>{failedCount} item gagal disinkronkan</span>
          <button
            type="button"
            onClick={discardFailedItems}
            className="px-2 py-1 rounded border border-red-300 bg-white text-red-700 hover:bg-red-100 min-h-[32px]"
          >
            Buang
          </button>
        </div>
      )}

      {/* Badge "Menunggu Sinkronisasi" */}
      {queueCount > 0 && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-4 z-40 bg-amber-100 border border-amber-300 text-amber-800 rounded-lg px-3 py-2 text-sm font-medium shadow-md transition-all duration-200 flex items-center gap-2"
        >
          {/* Animasi loading spinner */}
          <svg
            className="w-4 h-4 animate-spin"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          <span>
            Menunggu Sinkronisasi ({queueCount}{" "}
            {queueCount === 1 ? "item" : "item"})
          </span>
        </div>
      )}
    </>
  );
}

export default OfflineIndicator;
