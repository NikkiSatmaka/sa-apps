import { qualificationBadgeClass, statusBadgeClass } from "@/lib/status";

/**
 * Badge `status` proyek. Saat `status = Intake`, `qualification_state` ikut tampil sebagai badge
 * kedua (ADR 0013); di luar Intake nilainya tidak bermakna sehingga disembunyikan.
 */
export interface StatusBadgeProps {
  status: string;
  qualificationState?: string | null;
  /** Kelas tambahan untuk badge `status` (ukuran/bentuk mengikuti konteks pemakaian). */
  className?: string;
}

export function StatusBadge({ status, qualificationState, className = "px-2 py-0.5 rounded text-xs" }: StatusBadgeProps) {
  const tampilkanState = status === "Intake" && !!qualificationState;
  return (
    <>
      <span className={`inline-block font-medium whitespace-nowrap ${className} ${statusBadgeClass(status)}`}>
        {status}
      </span>
      {tampilkanState && (
        <span
          title={`Kualifikasi: ${qualificationState}`}
          className={`inline-block font-medium whitespace-nowrap ${className} ${qualificationBadgeClass(qualificationState)}`}
        >
          {qualificationState}
        </span>
      )}
    </>
  );
}
