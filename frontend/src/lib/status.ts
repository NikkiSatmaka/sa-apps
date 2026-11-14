/**
 * Model status proyek dua field (ADR 0013, spec §2.0 "Siklus status").
 * STUB: diisi pada commit implementasi.
 */
import type { Actor } from "./roles";

export const STATUS_PROYEK: readonly string[] = [];
export const QUALIFICATION_STATE: readonly string[] = [];

export type KunciAksi =
  | "submitted"
  | "revisi"
  | "won"
  | "jeda"
  | "lanjut"
  | "lost"
  | "closed"
  | "buka_kembali";

export interface AksiStatus {
  kunci: KunciAksi;
  label: string;
  newStatus: string;
  butuhAlasan: boolean;
}

export interface KonteksAksi {
  actor: (Actor & { id?: string | null }) | null | undefined;
  status: string;
  previousStatus?: string | null;
  salesPicId?: string | null;
  productPicId?: string | null;
  /** id SA utama dan SA tambahan project. */
  saIds?: ReadonlyArray<string | null | undefined>;
}

export function aksiStatusTersedia(_k: KonteksAksi): AksiStatus[] {
  return [];
}

export function statusBadgeClass(_status: string): string {
  return "";
}

export function qualificationBadgeClass(_state: string): string {
  return "";
}
