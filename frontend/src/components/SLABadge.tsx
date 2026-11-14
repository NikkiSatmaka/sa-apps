"use client";

/**
 * Komponen SLA Badge — Menampilkan countdown SLA DQ Number
 *
 * Warna badge berdasarkan hari yang berlalu:
 * - Hijau (0-2 hari): Normal, masih dalam batas
 * - Kuning (3-4 hari): Warning, reminder sudah dikirim
 * - Merah (5+ hari): Kritis, auto-lock sudah terjadi
 *
 * Requirements: 16.7
 */

/** Props untuk SLABadge */
export interface SLABadgeProps {
  /** Jumlah hari yang berlalu sejak assignment */
  daysElapsed: number;
  /** Apakah folder Solutions sudah di-lock */
  isLocked: boolean;
  /** Apakah timer dijeda (proyek On Hold) */
  isPaused?: boolean;
}

/**
 * Menentukan warna badge berdasarkan hari yang berlalu
 */
function getBadgeStyle(daysElapsed: number): string {
  if (daysElapsed <= 2) {
    return "bg-green-100 text-green-800 border-green-200";
  }
  if (daysElapsed <= 4) {
    return "bg-yellow-100 text-yellow-800 border-yellow-200";
  }
  return "bg-red-100 text-red-800 border-red-200";
}

/**
 * Ikon lock (ditampilkan jika folder terkunci)
 */
function LockIcon() {
  return (
    <svg
      className="w-3 h-3 inline-block mr-0.5"
      fill="currentColor"
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export function SLABadge({ daysElapsed, isLocked }: SLABadgeProps) {
  const badgeStyle = getBadgeStyle(daysElapsed);

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${badgeStyle}`}
      title={`SLA DQ Number: H+${daysElapsed} hari${isLocked ? " (folder terkunci)" : ""}`}
      aria-label={`SLA countdown: H+${daysElapsed} hari${isLocked ? ", folder terkunci" : ""}`}
    >
      {isLocked && <LockIcon />}
      <span>H+{daysElapsed}</span>
    </span>
  );
}
