/** Stub (fase merah): diisi pada commit implementasi. */
import type { Actor } from "./roles";

export const TINGKAT_AKSES = [
  "tulis",
  "ubah_proyek",
  "kelola",
  "isi_dq",
  "tambah_kolaborator",
  "hapus_kolaborator",
  "handover",
  "kelola_requirement",
  "edit_kuesioner",
  "kelola_tim_sa",
  "komentar",
  "buat_subtask",
] as const;

export type TingkatAkses = (typeof TINGKAT_AKSES)[number];

export interface HubunganProyek {
  actor: (Actor & { id?: string | null }) | null | undefined;
  salesPicId?: string | null;
  productPicId?: string | null;
  saIds?: ReadonlyArray<string | null | undefined> | null;
  kolaborator?: ReadonlyArray<{ user_id: string; role?: string | null }>;
}

export function izinkan(_tingkat: TingkatAkses, _h: HubunganProyek): boolean {
  return false;
}
