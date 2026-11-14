/** Badge `status` (+ `qualification_state` saat Intake). STUB: diisi pada commit implementasi. */
export interface StatusBadgeProps {
  status: string;
  qualificationState?: string | null;
  className?: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span>{status}</span>;
}
