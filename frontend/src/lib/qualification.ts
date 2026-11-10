/**
 * Kuesioner kualifikasi v1 — tipe, pilihan, dan label pertanyaan.
 *
 * Pilihan HARUS identik dengan backend (backend/app/services/bant_rubric.py).
 * Skor dihitung backend dari jawaban ini; frontend tidak menghitung skor apa pun.
 */

export const QUESTIONNAIRE_SCHEMA_VERSION = 1;

export const BUDGET_DIALOKASIKAN_CHOICES = ["Ya", "Belum", "Tidak tahu"] as const;
export const PERAN_PIC_CHOICES = ["Pengambil keputusan", "Perantara", "Tidak tahu"] as const;
export const JENIS_WORKLOAD_CHOICES = [
  "Migrasi ke cloud",
  "Data warehouse/analytics",
  "Disaster recovery/backup",
  "Aplikasi baru/modernisasi",
  "Keamanan",
  "Lainnya",
] as const;
export const LINGKUNGAN_CHOICES = ["On-prem", "Cloud", "Hybrid"] as const;
export const TARGET_GO_LIVE_CHOICES = ["≤ 3 bulan", "≤ 6 bulan", "> 6 bulan", "Tidak tahu"] as const;

/** Jawaban kuesioner di form: semua string agar mudah dikontrol; "" = belum diisi. */
export interface QualificationAnswers {
  mrr: string;
  budget_dialokasikan: string;
  pic_nama: string;
  pic_jabatan: string;
  pic_email: string;
  peran_pic: string;
  stakeholder_lain: string;
  masalah_bisnis: string;
  jenis_workload: string;
  lingkungan: string;
  skala: string;
  persyaratan_khusus: string;
  kompetitor: string;
  target_go_live: string;
}

export type QualificationErrors = Partial<Record<keyof QualificationAnswers, string>>;

export const EMPTY_ANSWERS: QualificationAnswers = {
  mrr: "",
  budget_dialokasikan: "",
  pic_nama: "",
  pic_jabatan: "",
  pic_email: "",
  peran_pic: "",
  stakeholder_lain: "",
  masalah_bisnis: "",
  jenis_workload: "",
  lingkungan: "",
  skala: "",
  persyaratan_khusus: "",
  kompetitor: "",
  target_go_live: "",
};

/** Field wajib (pertanyaan #11 Target submit ada di langkah 1). */
const REQUIRED: (keyof QualificationAnswers)[] = [
  "budget_dialokasikan",
  "peran_pic",
  "masalah_bisnis",
  "jenis_workload",
  "lingkungan",
  "skala",
  "target_go_live",
];

/** Validasi kelengkapan di sisi klien (hanya umpan balik cepat; backend tetap memvalidasi). */
export function validateAnswers(a: QualificationAnswers): QualificationErrors {
  const errors: QualificationErrors = {};
  for (const key of REQUIRED) {
    if (!a[key].trim()) errors[key] = "Wajib diisi";
  }
  if (a.mrr.trim() && !(Number(a.mrr) >= 0)) errors.mrr = "Harus berupa angka";
  if (a.pic_email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a.pic_email.trim())) {
    errors.pic_email = "Format email tidak valid";
  }
  return errors;
}

/** Bentuk payload JSON yang dikirim ke backend (string kosong → null, MRR → angka). */
export function toPayload(a: QualificationAnswers): Record<string, string | number | null> {
  const out: Record<string, string | number | null> = {};
  for (const [key, value] of Object.entries(a)) {
    const trimmed = value.trim();
    out[key] = trimmed === "" ? null : key === "mrr" ? Number(trimmed) : trimmed;
  }
  return out;
}

/** Label pertanyaan kuesioner untuk tampilan read-only (urutan = urutan tampil). */
export const ANSWER_LABELS: [keyof QualificationAnswers, string][] = [
  ["mrr", "MRR (IDR)"],
  ["budget_dialokasikan", "Budget sudah dialokasikan/disetujui?"],
  ["pic_nama", "Nama PIC"],
  ["pic_jabatan", "Jabatan PIC"],
  ["pic_email", "Email PIC"],
  ["peran_pic", "Peran PIC dalam keputusan"],
  ["stakeholder_lain", "Stakeholder lain dalam keputusan"],
  ["masalah_bisnis", "Masalah bisnis yang ingin diselesaikan"],
  ["jenis_workload", "Jenis workload"],
  ["lingkungan", "Lingkungan saat ini"],
  ["skala", "Skala (jumlah server, volume data)"],
  ["persyaratan_khusus", "Persyaratan khusus"],
  ["kompetitor", "Kompetitor/vendor lain"],
  ["target_go_live", "Target go-live / keputusan beli"],
];

/** Bagian `qualification` dari GET /projects/{id} (dihitung backend; read-only). */
export interface QualificationView {
  legacy: boolean;
  schema_version: number | null;
  answers: Record<string, string | number | null> | null;
  sub_scores: { budget: number; authority: number; need: number; timeline: number } | null;
  feedback: string | null;
  legacy_data: {
    budget_mrr?: number | null;
    pic_name?: string | null;
    pic_position?: string | null;
    pic_email?: string | null;
    need_description?: string | null;
    timeline_target?: string | null;
  } | null;
}
