"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "./LoadError";
import {
  AvailableSA,
  PendingProject,
  assignProject,
} from "@/lib/api/assignment";

/**
 * Modal Assignment — Digunakan oleh Lead_SA untuk menugaskan SA ke proyek
 *
 * Fitur:
 * - Menampilkan daftar SA tersedia dengan workload (jumlah proyek aktif)
 * - Indikator workload: hijau (0-2), kuning (3-4), merah (5+)
 * - Konfirmasi sebelum assignment
 * - Loading state dan success notification
 *
 * Requirements: 4.1, 4.2
 */

interface AssignmentModalProps {
  /** Proyek yang akan di-assign */
  project: PendingProject;
  /** Callback ketika modal ditutup */
  onClose: () => void;
  /** Callback setelah assignment berhasil */
  onSuccess: () => void;
}

export function AssignmentModal({
  project,
  onClose,
  onSuccess,
}: AssignmentModalProps) {
  const [selectedSA, setSelectedSA] = useState<string | null>(null);
  const [isAssigning, setIsAssigning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch daftar SA tersedia
  const {
    data: saList,
    isLoading: isLoadingSA,
    error: saError,
    mutate: mutateSA,
  } = useSWR<AvailableSA[]>(
    "/sa/available",
    fetcher
  );

  /**
   * Handler konfirmasi assignment
   * Memanggil API assign dan trigger callback on success
   */
  const handleAssign = async () => {
    if (!selectedSA) return;

    setIsAssigning(true);
    setError(null);

    try {
      await assignProject(project.id_project, selectedSA);
      onSuccess();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Gagal melakukan assignment";
      setError(message);
    } finally {
      setIsAssigning(false);
    }
  };

  /**
   * Tentukan warna workload indicator berdasarkan jumlah proyek aktif
   * 0-2: hijau (rendah), 3-4: kuning (sedang), 5+: merah (tinggi)
   */
  const getWorkloadColor = (count: number) => {
    if (count <= 2) return "bg-green-100 text-green-700";
    if (count <= 4) return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };

  const getWorkloadLabel = (count: number) => {
    if (count <= 2) return "Rendah";
    if (count <= 4) return "Sedang";
    return "Tinggi";
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Overlay backdrop */}
      <div
        className="absolute inset-0 bg-black/40 transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal content */}
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-neutral-200">
          <div>
            <h2 className="text-lg font-semibold text-neutral-900">
              Assign SA ke Proyek
            </h2>
            <p className="text-sm text-neutral-500 mt-0.5">
              {project.project_name} — {project.customer_name}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-[44px] h-[44px] rounded-lg
                       hover:bg-neutral-100 transition-colors duration-100"
            aria-label="Tutup modal"
          >
            <svg
              className="w-5 h-5 text-neutral-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Body — daftar SA */}
        <div className="flex-1 overflow-y-auto p-5">
          {/* Info BANT Status */}
          <div className="mb-4 p-3 bg-neutral-50 rounded-lg">
            <div className="flex items-center gap-4 text-sm">
              <span className="text-neutral-500">BANT Status:</span>
              <span className={`font-semibold ${
                project.bant_score >= 60 ? "text-green-600" : "text-amber-600"
              }`}>
                {project.bant_score >= 60 ? "Passed" : "Not Passed"}
              </span>
              {project.use_case_tags.length > 0 && (
                <div className="flex gap-1.5 flex-wrap">
                  {project.use_case_tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 bg-primary-50 text-primary-600 text-xs rounded-full"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Label */}
          <p className="text-sm font-medium text-neutral-700 mb-3">
            Pilih Solutions Architect:
          </p>

          {/* Loading skeleton */}
          {isLoadingSA && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 p-3 rounded-lg border border-neutral-100"
                >
                  <div className="w-10 h-10 rounded-full bg-neutral-200 animate-pulse" />
                  <div className="flex-1">
                    <div className="h-4 w-32 bg-neutral-200 rounded animate-pulse mb-1" />
                    <div className="h-3 w-48 bg-neutral-100 rounded animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {saError && !saList && (
            <LoadError message="Gagal memuat daftar SA." onRetry={() => mutateSA()} />
          )}

          {/* Daftar SA */}
          {!isLoadingSA && saList && (
            <div className="space-y-2">
              {saList.length === 0 && (
                <p className="text-sm text-neutral-500 text-center py-4">
                  Tidak ada SA yang tersedia saat ini.
                </p>
              )}
              {saList.map((sa) => (
                <button
                  key={sa.id}
                  type="button"
                  onClick={() => setSelectedSA(sa.id)}
                  className={`
                    w-full flex items-center gap-3 p-3 rounded-lg border text-left
                    transition-all duration-100
                    ${
                      selectedSA === sa.id
                        ? "border-primary-500 bg-primary-50 ring-1 ring-primary-500"
                        : "border-neutral-200 hover:border-neutral-300 hover:bg-neutral-50"
                    }
                  `}
                >
                  {/* Avatar */}
                  <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center shrink-0">
                    {sa.avatar_url ? (
                      <img
                        src={sa.avatar_url}
                        alt={sa.name}
                        className="w-10 h-10 rounded-full object-cover"
                      />
                    ) : (
                      <span className="text-sm font-medium text-primary-600">
                        {sa.name.charAt(0).toUpperCase()}
                      </span>
                    )}
                  </div>

                  {/* Info SA */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-neutral-900 truncate">
                      {sa.name}
                    </p>
                    <p className="text-xs text-neutral-500 truncate">
                      {sa.email}
                    </p>
                  </div>

                  {/* Workload badge */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={`
                        px-2 py-1 text-xs font-medium rounded-full
                        ${getWorkloadColor(sa.active_project_count)}
                      `}
                    >
                      {sa.active_project_count} proyek
                    </span>
                    <span
                      className={`
                        text-xs font-medium
                        ${getWorkloadColor(sa.active_project_count).split(" ")[1]}
                      `}
                    >
                      {getWorkloadLabel(sa.active_project_count)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}
        </div>

        {/* Footer — tombol aksi */}
        <div className="flex items-center justify-end gap-3 p-5 border-t border-neutral-200">
          <button
            onClick={onClose}
            disabled={isAssigning}
            className="px-4 py-2 text-sm font-medium text-neutral-700 bg-white
                       border border-neutral-300 rounded-lg hover:bg-neutral-50
                       transition-colors duration-100 min-h-[44px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Batal
          </button>
          <button
            onClick={handleAssign}
            disabled={!selectedSA || isAssigning}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600
                       rounded-lg hover:bg-primary-700 transition-colors duration-100
                       min-h-[44px] disabled:opacity-50 disabled:cursor-not-allowed
                       flex items-center gap-2"
          >
            {isAssigning ? (
              <>
                <svg
                  className="animate-spin w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
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
                Mengassign...
              </>
            ) : (
              "Konfirmasi Assignment"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
