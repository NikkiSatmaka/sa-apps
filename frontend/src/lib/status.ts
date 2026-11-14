/**
 * Model status proyek dua field (ADR 0013, spec §2.0 "Siklus status").
 *
 * - `status`: siklus kerja + status samping `Lost` dan `On Hold`.
 * - `qualification_state`: gate kualifikasi, hanya bermakna saat `status = Intake`.
 *
 * Hak per transisi mencerminkan `backend/app/api/workflow.py` (`TRANSISI_HAK`, `_STATUS_KEMBALI`).
 * Backend tetap penentu akhir (403/400/409); UI hanya menyembunyikan tombol yang pasti ditolak.
 */
import { isAdmin, isPrivileged, isRequester, type Actor } from "./roles";

export const STATUS_PROYEK = [
  "Intake",
  "Awaiting Assignment",
  "Assigned",
  "In Progress",
  "Submitted",
  "Won",
  "Handed Over",
  "Closed",
  "Lost",
  "On Hold",
] as const;

export const QUALIFICATION_STATE = ["Scoring", "Need Clarification", "Manual Review", "Qualified"] as const;

/** Status yang boleh dijeda: dari `Awaiting Assignment` sampai `Submitted` (ADR 0013). */
const BOLEH_DIJEDA: readonly string[] = ["Awaiting Assignment", "Assigned", "In Progress", "Submitted"];

/** Status yang boleh menjadi `Lost`: semua sebelum `Handed Over` (termasuk `On Hold`). */
const BOLEH_LOST: readonly string[] = [
  "Intake",
  "Awaiting Assignment",
  "Assigned",
  "In Progress",
  "Submitted",
  "Won",
  "On Hold",
];

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
  /** Nilai `new_status` untuk `PATCH /projects/{id}/status`. */
  newStatus: string;
  /** True bila `reason` wajib (Lost, buka kembali). */
  butuhAlasan: boolean;
}

export interface KonteksAksi {
  actor: (Actor & { id?: string | null }) | null | undefined;
  status: string;
  /** Tujuan lanjut/buka kembali (`previous_status` dari detail proyek). */
  previousStatus?: string | null;
  salesPicId?: string | null;
  productPicId?: string | null;
  /** id SA utama dan SA tambahan project. */
  saIds?: ReadonlyArray<string | null | undefined>;
}

/**
 * Aksi status yang tampil untuk aktor pada status sekarang. `Awaiting Assignment` → `Assigned`
 * (POST /assign) dan `Won` → `Handed Over` (POST /handover) punya tombolnya sendiri; `In Progress`
 * otomatis dari backend sehingga tidak ada di sini.
 */
export function aksiStatusTersedia(k: KonteksAksi): AksiStatus[] {
  const { actor, status } = k;
  if (!actor) return [];

  const privileged = isPrivileged(actor);
  const id = actor.id ?? null;
  // Hak "SA ditugaskan": cocok id DAN peran SA (utama atau tambahan), sama seperti backend.
  const saDitugaskan = actor.role === "SA" && id !== null && (k.saIds ?? []).includes(id);
  const bisaSa = privileged || saDitugaskan;
  // Hak "PIC": Sales/Product PIC project itu (id DAN peran requester).
  const picProyek = isRequester(actor) && id !== null && (id === k.salesPicId || id === k.productPicId);
  const bisaPic = privileged || picProyek;

  const aksi: AksiStatus[] = [];
  const tambah = (kunci: KunciAksi, label: string, newStatus: string, butuhAlasan = false) =>
    aksi.push({ kunci, label, newStatus, butuhAlasan });

  if ((status === "Assigned" || status === "In Progress") && bisaSa) {
    tambah("submitted", "Tandai Submitted", "Submitted");
  }
  if (status === "Submitted" && bisaSa) tambah("revisi", "Minta Revisi", "In Progress");
  if (status === "Submitted" && bisaPic) tambah("won", "Tandai Won", "Won");
  if (BOLEH_DIJEDA.includes(status) && bisaPic) tambah("jeda", "Jeda (On Hold)", "On Hold");
  if (status === "On Hold" && k.previousStatus && bisaPic) tambah("lanjut", "Lanjutkan", k.previousStatus);
  if (BOLEH_LOST.includes(status) && privileged) tambah("lost", "Tandai Lost", "Lost", true);
  if (status === "Handed Over" && privileged) tambah("closed", "Tutup Proyek (Closed)", "Closed");
  if ((status === "Closed" || status === "Lost") && k.previousStatus && isAdmin(actor)) {
    tambah("buka_kembali", "Buka Kembali", k.previousStatus, true);
  }
  return aksi;
}

const BADGE_STATUS: Record<string, string> = {
  Intake: "bg-neutral-100 text-neutral-700",
  "Awaiting Assignment": "bg-yellow-100 text-yellow-800",
  Assigned: "bg-blue-100 text-blue-800",
  "In Progress": "bg-indigo-100 text-indigo-800",
  Submitted: "bg-green-100 text-green-800",
  Won: "bg-emerald-100 text-emerald-800",
  "Handed Over": "bg-teal-100 text-teal-800",
  Closed: "bg-slate-200 text-slate-700",
  Lost: "bg-red-100 text-red-800",
  "On Hold": "bg-amber-100 text-amber-800",
};

const BADGE_QUALIFICATION: Record<string, string> = {
  Scoring: "bg-purple-100 text-purple-800",
  "Need Clarification": "bg-orange-100 text-orange-800",
  "Manual Review": "bg-pink-100 text-pink-800",
  Qualified: "bg-green-100 text-green-800",
};

const BADGE_NETRAL = "bg-neutral-100 text-neutral-700";

/** Kelas warna badge `status`; nilai tak dikenal jatuh ke netral. */
export function statusBadgeClass(status: string): string {
  return BADGE_STATUS[status] ?? BADGE_NETRAL;
}

/** Kelas warna badge `qualification_state`; nilai tak dikenal jatuh ke netral. */
export function qualificationBadgeClass(state: string): string {
  return BADGE_QUALIFICATION[state] ?? BADGE_NETRAL;
}
