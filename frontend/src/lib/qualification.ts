/**
 * Kuesioner kualifikasi — tipe & util sisi klien.
 *
 * Definisi (nama field, label, tipe, wajib, pilihan, petunjuk, tata letak) TIDAK disimpan di
 * sini: seluruhnya dimuat dari backend lewat GET /qualification/schema (satu sumber definisi).
 * Validasi klien hanya umpan balik cepat yang diturunkan dari skema; backend tetap otoritatif.
 * Skor dihitung backend; frontend tidak menghitung skor apa pun.
 */

import useSWR from "swr";
import { fetcher } from "./fetcher";
import { isPrivileged, isRequester, type Actor } from "./roles";

export type QuestionType = "number" | "choice" | "text" | "short" | "email" | "date";

export interface QuestionDef {
  name: string;
  group: string;
  type: QuestionType;
  label: string;
  short_label: string;
  required: boolean;
  choices: string[] | null;
  hint: string | null;
  placeholder: string | null;
  max_length: number | null;
  min_value: number | null;
  max_value: number | null;
  pattern: string | null;
  row: string | null;
  row_hint: string | null;
  display: "currency_idr" | "date" | null;
  show_char_count: boolean;
  /** True: field header proyek (bukan bagian jawaban); hanya tampil di baca-saja. */
  header: boolean;
}

export interface QualificationSchema {
  schema_version: number;
  groups: { key: string; title: string }[];
  questions: QuestionDef[];
}

/** Muat skema kuesioner dari backend (statis per versi; tidak perlu revalidasi sering). */
export function useQualificationSchema() {
  const { data, error, isLoading } = useSWR<QualificationSchema>("/qualification/schema", fetcher, {
    revalidateOnFocus: false,
  });
  return { schema: data, error, isLoading };
}

/** Jawaban kuesioner di form: semua string agar mudah dikontrol; ""/tidak ada = belum diisi. */
export type QualificationAnswers = Record<string, string>;
export type QualificationErrors = Record<string, string | undefined>;

/** Pertanyaan yang jawabannya dikirim ke backend (tanpa field header). */
export function answerQuestions(schema: QualificationSchema): QuestionDef[] {
  return schema.questions.filter((q) => !q.header);
}

/** Baris tata letak: pertanyaan berurutan dengan `row` sama dikelompokkan sebaris. */
export interface LayoutRow {
  questions: QuestionDef[];
  hint: string | null;
}

/** Susun pertanyaan sebuah kelompok BANT menjadi baris sesuai petunjuk tata letak skema. */
export function layoutRows(schema: QualificationSchema, groupKey: string): LayoutRow[] {
  const rows: LayoutRow[] = [];
  for (const q of answerQuestions(schema).filter((x) => x.group === groupKey)) {
    const last = rows[rows.length - 1];
    if (q.row && last && last.questions[0].row === q.row) {
      last.questions.push(q);
      last.hint = last.hint ?? q.row_hint;
    } else {
      rows.push({ questions: [q], hint: q.row_hint });
    }
  }
  return rows;
}

/** Validasi di sisi klien, diturunkan dari skema (hanya umpan balik cepat; backend tetap memvalidasi). */
export function validateAnswers(schema: QualificationSchema, a: QualificationAnswers): QualificationErrors {
  const errors: QualificationErrors = {};
  for (const q of answerQuestions(schema)) {
    const v = (a[q.name] ?? "").trim();
    if (!v) {
      if (q.required) errors[q.name] = "Wajib diisi";
      continue;
    }
    if (q.type === "number") {
      const n = Number(v);
      if (!Number.isFinite(n)) errors[q.name] = "Harus berupa angka";
      else if ((q.min_value !== null && n < q.min_value) || (q.max_value !== null && n > q.max_value)) {
        errors[q.name] = `Harus antara ${q.min_value ?? "-∞"} dan ${q.max_value ?? "∞"}`;
      }
    } else if (q.type === "choice") {
      if (!q.choices?.includes(v)) errors[q.name] = "Pilihan tidak valid";
    } else {
      if (q.max_length !== null && v.length > q.max_length) errors[q.name] = `Maksimal ${q.max_length} karakter`;
      else if (q.pattern && !new RegExp(q.pattern).test(v)) {
        errors[q.name] = q.type === "email" ? "Format email tidak valid" : "Format tidak valid";
      }
    }
  }
  return errors;
}

/** Bentuk payload JSON ke backend (string kosong → null, tipe number → angka). */
export function toPayload(
  schema: QualificationSchema,
  a: QualificationAnswers
): Record<string, string | number | null> {
  const out: Record<string, string | number | null> = {};
  for (const q of answerQuestions(schema)) {
    const trimmed = (a[q.name] ?? "").trim();
    out[q.name] = trimmed === "" ? null : q.type === "number" ? Number(trimmed) : trimmed;
  }
  return out;
}

/** Bagian `qualification` dari GET /projects/{id} (dihitung backend; read-only). */
export interface QualificationView {
  legacy: boolean;
  /** True selama status Scoring Pending: skor/feedback belum final dan disembunyikan. */
  scoring_pending?: boolean;
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

/** Status ketika jawaban kuesioner boleh diedit Sales PIC (dan memicu re-score). */
export const EDITABLE_STATUS = "Need Clarification";
/** Status sebelum/di luar gate yang menolak edit jawaban (menunggu scoring/review). */
const LOCKED_STATUSES = ["New", "Scoring Pending", "Manual Review Required"];

export type AnswerEditMode = "rescore" | "correct" | "none";

/**
 * Mode edit jawaban kuesioner (mencerminkan aturan backend; backend tetap penentu):
 * - "rescore": Need Clarification untuk Sales/Product PIC, Lead_SA, atau admin → skor dihitung ulang.
 * - "correct": Lead_SA/admin setelah lolos gate → koreksi tanpa re-score.
 * - "none": selain itu (kontrol edit tidak ditampilkan).
 */
export function answerEditMode(
  user: (Actor & { id?: string }) | null | undefined,
  picIds: string | null | undefined | ReadonlyArray<string | null | undefined>,
  status: string,
  _qualificationState?: string | null
): AnswerEditMode {
  const privileged = isPrivileged(user);
  // PIC project: Product PIC (selalu ada) atau Sales PIC (opsional), ADR 0014. Pembuat yang bukan
  // PIC tidak mendapat hak sendiri.
  const pics = Array.isArray(picIds) ? picIds : [picIds];
  const isPic = isRequester(user) && !!user?.id && pics.includes(user.id);
  if (!privileged && !isPic) return "none";
  if (status === EDITABLE_STATUS) return "rescore";
  if (privileged && !LOCKED_STATUSES.includes(status)) return "correct";
  return "none";
}

/** Ubah jawaban dari backend (string | number | null) menjadi state form. */
export function answersFromView(
  schema: QualificationSchema,
  answers: Record<string, string | number | null> | null
): QualificationAnswers {
  const out: QualificationAnswers = {};
  for (const q of answerQuestions(schema)) {
    const v = answers?.[q.name];
    out[q.name] = v === null || v === undefined ? "" : String(v);
  }
  return out;
}
