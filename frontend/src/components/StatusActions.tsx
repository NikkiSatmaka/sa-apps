"use client";

/** Tombol aksi status proyek (spec §2.0). STUB: diisi pada commit implementasi. */
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
  onChanged: () => void;
}

export function StatusActions(_props: StatusActionsProps) {
  return null;
}
