"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  getRequirementStatus,
  regenerateRequirement,
} from "@/lib/api/documents";

/**
 * Status generate Requirement + tombol "Generate ulang" / "Coba lagi" (#34).
 *
 * - pending: keterangan + polling sederhana (3 dtk) sampai selesai.
 * - failed: pesan jelas + tombol coba lagi (endpoint yang sama dengan generate ulang).
 * - ready: tombol "Generate ulang" (hanya untuk peran yang diizinkan backend).
 * Peringatan teks terpotong ada di RequirementItemsView.
 */

const POLL_INTERVAL_MS = 3000;

interface RequirementRegenerateSectionProps {
  projectId: string;
  /** Dipanggil saat generate selesai agar daftar dokumen dimuat ulang */
  onChanged?: () => void;
}

export function RequirementRegenerateSection({
  projectId,
  onChanged,
}: RequirementRegenerateSectionProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data, mutate } = useSWR(
    `/projects/${projectId}/requirement-status`,
    () => getRequirementStatus(projectId),
    {
      refreshInterval: (latest) =>
        latest?.requirement_generation_status === "pending"
          ? POLL_INTERVAL_MS
          : 0,
    }
  );

  const status = data?.requirement_generation_status ?? null;
  const prevStatus = useRef(status);
  useEffect(() => {
    if (prevStatus.current === "pending" && status !== "pending") {
      onChanged?.();
    }
    prevStatus.current = status;
  }, [status, onChanged]);

  // Tidak ada Requirement untuk proyek yang belum lolos gate
  if (!data || status === null) return null;

  const handleRegenerate = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await regenerateRequirement(projectId);
      await mutate();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Gagal memulai generate ulang."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const canRegenerate = data.can_regenerate_requirement;
  const buttonClass =
    "px-3 py-1.5 rounded-lg text-sm font-medium border border-neutral-300 " +
    "text-neutral-700 hover:bg-neutral-50 disabled:opacity-50 min-h-[36px]";

  if (status === "pending") {
    return (
      <div
        className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800"
        role="status"
      >
        Requirement sedang dibuat… Halaman ini diperbarui otomatis saat selesai.
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-center justify-between gap-3"
        role="alert"
      >
        <span>
          Requirement gagal dibuat. Konten sebelumnya (bila ada) tidak berubah.
          {!canRegenerate && " Hubungi SA yang ditugaskan, Lead SA, atau Admin."}
          {error && <span className="block mt-1">{error}</span>}
        </span>
        {canRegenerate && (
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={submitting}
            className={buttonClass}
          >
            {submitting ? "Memulai..." : "Coba lagi"}
          </button>
        )}
      </div>
    );
  }

  if (!canRegenerate) return null;

  return (
    <div className="flex items-center justify-between gap-3 text-sm text-neutral-600">
      <span>
        Generate ulang menimpa butir Requirement dan menghapus perubahan manual.
        {error && <span className="block text-red-600">{error}</span>}
      </span>
      <button
        type="button"
        onClick={handleRegenerate}
        disabled={submitting}
        className={buttonClass}
      >
        {submitting ? "Memulai..." : "Generate ulang"}
      </button>
    </div>
  );
}
