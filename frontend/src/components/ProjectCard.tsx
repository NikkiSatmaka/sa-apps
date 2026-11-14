"use client";

import { SLABadge } from "@/components/SLABadge";
import { StatusBadge } from "@/components/StatusBadge";

/**
 * Komponen Project Card — reusable card untuk menampilkan ringkasan proyek
 *
 * Fitur:
 * - Badge "Menunggu DQ" ketika dq_number null
 * - Badge status proyek dengan warna sesuai
 * - Informasi: nama proyek, nama customer, status, tanggal update
 * - Touch target min 44x44px
 * - Klik untuk navigasi ke detail proyek
 *
 * Requirements: 6.2, 9.1, 9.2
 */

/** Props untuk ProjectCard */
export interface ProjectCardProps {
  /** ID proyek */
  id: string;
  /** Nama proyek */
  projectName: string;
  /** Nama customer */
  customerName: string;
  /** Status proyek saat ini */
  status: string;
  /** DQ Number (null jika belum diset) */
  dqNumber: string | null;
  /** Tanggal terakhir update (ISO string) */
  lastUpdated: string;
  /** BANT Score (opsional) */
  bantScore?: number | null;
  /** SLA days elapsed (opsional, ditampilkan jika ada) */
  slaDaysElapsed?: number | null;
  /** Apakah folder Solutions terkunci (SLA auto-lock) */
  slaIsLocked?: boolean;
  /** qualification_state (hanya ditampilkan saat Intake) */
  qualificationState?: string | null;
  /** Apakah timer SLA dijeda (On Hold) */
  slaIsPaused?: boolean;
  /** Callback saat card diklik */
  onClick?: () => void;
}

/**
 * Format tanggal ke format lokal Indonesia
 */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  // `toLocaleDateString` tidak melempar untuk tanggal tak valid (hasilnya "Invalid Date"),
  // jadi validasi eksplisit agar nilai kosong/rusak tidak tampil sebagai "Invalid Date".
  if (Number.isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function ProjectCard({
  id,
  projectName,
  customerName,
  status,
  dqNumber,
  lastUpdated,
  bantScore,
  slaDaysElapsed,
  slaIsLocked = false,
  qualificationState,
  slaIsPaused = false,
  onClick,
}: ProjectCardProps) {
  return (
    <article
      className="bg-white border border-neutral-200 rounded-lg p-4 hover:shadow-md 
                 hover:border-primary-200 transition-all duration-200 cursor-pointer
                 min-h-[44px]"
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={`Proyek ${projectName} - ${customerName}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
    >
      {/* Header: Nama proyek + badge */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-sm font-semibold text-neutral-900 line-clamp-2 flex-1">
          {projectName}
        </h3>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {/* Badge Status */}
          <StatusBadge status={status} qualificationState={qualificationState} />

          {/* Badge "Menunggu DQ" */}
          {dqNumber === null && (
            <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 whitespace-nowrap">
              Menunggu DQ
            </span>
          )}

          {/* SLA Badge — ditampilkan jika DQ belum diinput dan SLA aktif */}
          {slaDaysElapsed != null && dqNumber === null && (
            <SLABadge daysElapsed={slaDaysElapsed} isLocked={slaIsLocked} isPaused={slaIsPaused} />
          )}
        </div>
      </div>

      {/* Customer name */}
      <p className="text-sm text-neutral-600 mb-3">
        {customerName}
      </p>

      {/* Footer: Info tambahan */}
      <div className="flex items-center justify-between text-xs text-neutral-400">
        <span>Update: {formatDate(lastUpdated)}</span>
        {bantScore !== null && bantScore !== undefined && (
          <span
            className={`font-medium ${
              bantScore >= 60 ? "text-green-600" : "text-amber-600"
            }`}
          >
            {bantScore >= 60 ? "BANT Passed" : "BANT not passed"}
          </span>
        )}
      </div>

      {/* DQ Number jika sudah ada */}
      {dqNumber && (
        <div className="mt-2 pt-2 border-t border-neutral-100">
          <span className="text-xs text-neutral-500">
            DQ: <span className="font-mono text-neutral-700">{dqNumber}</span>
          </span>
        </div>
      )}
    </article>
  );
}
