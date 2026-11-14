/**
 * Hak tulis per proyek di UI. Cermin `TingkatAkses`/`_ATURAN` di
 * `backend/app/core/dependencies.py` (ADR 0011: baca terbuka, tulis dibatasi; spec §2.0).
 *
 * Backend tetap penentu akhir (403). Helper ini hanya dipakai untuk menyembunyikan kontrol tulis
 * yang pasti ditolak, jadi komponen memanggil `izinkan(...)` (atau `useAksesProyek`) dan tidak
 * membandingkan peran/id sendiri. Tingkat transisi status (`ubah_status_*`) tetap di
 * `lib/status.ts` (`aksiStatusTersedia`) karena bergantung pada status sekarang.
 *
 * Menambah tingkat = tambah nama di `TINGKAT_AKSES` + satu entri di `ATURAN` (sama seperti backend).
 */
import { isPrivileged, type Actor } from "./roles";

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

/** Data hubungan pengguna ke satu proyek, diambil dari data yang sudah dimuat halaman. */
export interface HubunganProyek {
  actor: (Actor & { id?: string | null }) | null | undefined;
  salesPicId?: string | null;
  productPicId?: string | null;
  /**
   * id SA utama dan SA tambahan. `null` = belum diketahui (mis. `/tim-sa` gagal dimuat): SA
   * berperan SA dibiarkan lolos (opsi konservatif, backend yang menolak).
   */
  saIds?: ReadonlyArray<string | null | undefined> | null;
  /** Collaborator proyek (`user_id` + `role`); peran kosong dianggap viewer. */
  kolaborator?: ReadonlyArray<{ user_id: string; role?: string | null }>;
}

interface Aturan {
  salesPic?: boolean;
  saDitugaskan?: boolean;
  /** Collaborator yang diizinkan: hanya contributor. */
  contributor?: boolean;
  /** Sales PIC hanya berperan Sales/Product, SA ditugaskan hanya berperan SA. */
  cocokkanPeran?: boolean;
}

// Lead_SA/Admin selalu berhak pada semua tingkat. Entri kosong = hanya mereka.
const ATURAN: Record<TingkatAkses, Aturan> = {
  tulis: { saDitugaskan: true, contributor: true },
  ubah_proyek: { salesPic: true, saDitugaskan: true, contributor: true },
  kelola: { saDitugaskan: true },
  isi_dq: { salesPic: true },
  tambah_kolaborator: { salesPic: true, saDitugaskan: true },
  hapus_kolaborator: { salesPic: true, saDitugaskan: true },
  handover: { saDitugaskan: true, cocokkanPeran: true },
  kelola_requirement: { saDitugaskan: true, cocokkanPeran: true },
  edit_kuesioner: { salesPic: true, cocokkanPeran: true },
  kelola_tim_sa: {},
  komentar: { salesPic: true, saDitugaskan: true, contributor: true },
  buat_subtask: { saDitugaskan: true, cocokkanPeran: true },
};

/** Fungsi keputusan murni: apakah `h.actor` boleh pada `tingkat` di proyek ini? */
export function izinkan(tingkat: TingkatAkses, h: HubunganProyek): boolean {
  const { actor } = h;
  if (!actor) return false;
  if (isPrivileged(actor)) return true;

  const aturan = ATURAN[tingkat];
  const id = actor.id ?? null;
  if (id === null) return false;

  if (aturan.salesPic && (id === h.salesPicId || id === h.productPicId)) {
    if (!aturan.cocokkanPeran || actor.role === "Sales" || actor.role === "Product") return true;
  }

  if (aturan.saDitugaskan && (!aturan.cocokkanPeran || actor.role === "SA")) {
    if (h.saIds === null) return actor.role === "SA";
    if ((h.saIds ?? []).includes(id)) return true;
  }

  if (aturan.contributor) {
    const kolab = (h.kolaborator ?? []).find((k) => k.user_id === id);
    if (kolab && kolab.role === "contributor") return true;
  }
  return false;
}
