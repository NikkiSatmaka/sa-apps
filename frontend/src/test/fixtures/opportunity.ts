import type { QualificationSchema, QualificationView } from "@/lib/qualification";
import { makeQuestion } from "./qualification";

/**
 * Fixture tiket F4 (kuesioner + pembuatan/edit opportunity): skema kuesioner lengkap
 * (semua tipe pertanyaan, baris 2 kolom, field header) dan detail proyek untuk halaman edit.
 */
export function makeOpportunitySchema(overrides: Partial<QualificationSchema> = {}): QualificationSchema {
  return {
    schema_version: 1,
    groups: [
      { key: "budget", title: "Budget" },
      { key: "authority", title: "Authority" },
      { key: "need", title: "Need" },
      { key: "empty", title: "Kelompok Kosong" },
    ],
    questions: [
      makeQuestion({
        name: "budget_mrr",
        group: "budget",
        type: "number",
        label: "Anggaran bulanan (MRR)",
        short_label: "Budget MRR",
        min_value: 1,
        max_value: 1000,
        hint: "Dalam juta rupiah",
        display: "currency_idr",
      }),
      makeQuestion({
        name: "budget_status",
        group: "budget",
        type: "choice",
        label: "Status anggaran",
        short_label: "Status anggaran",
        choices: ["Sudah disetujui", "Dalam proses"],
      }),
      makeQuestion({
        name: "pic_name",
        group: "authority",
        type: "short",
        label: "Nama PIC",
        short_label: "Nama PIC",
        row: "pic",
        row_hint: "Kontak pengambil keputusan",
        max_length: 20,
        placeholder: "Nama lengkap",
      }),
      makeQuestion({
        name: "pic_email",
        group: "authority",
        type: "email",
        label: "Email PIC",
        short_label: "Email PIC",
        row: "pic",
        pattern: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
        required: false,
      }),
      makeQuestion({
        name: "need_description",
        group: "need",
        type: "text",
        label: "Kebutuhan teknis",
        short_label: "Kebutuhan",
        show_char_count: true,
        hint: "Jelaskan singkat",
        placeholder: "Uraian kebutuhan",
        max_length: 500,
      }),
      makeQuestion({
        name: "need_note",
        group: "need",
        type: "text",
        label: "Catatan kebutuhan",
        short_label: "Catatan",
        required: false,
        max_length: null,
      }),
      makeQuestion({
        name: "timeline_date",
        group: "need",
        type: "date",
        label: "Tanggal go-live",
        short_label: "Go-live",
        required: false,
        display: "date",
      }),
      makeQuestion({
        name: "target_submit",
        group: "need",
        type: "date",
        label: "Target submit",
        short_label: "Target submit",
        header: true,
        display: "date",
      }),
    ],
    ...overrides,
  };
}

/** Jawaban valid untuk skema `makeOpportunitySchema` (bentuk `QualificationView.answers`). */
export function makeAnswers(overrides: Record<string, string | number | null> = {}) {
  return {
    budget_mrr: 50,
    budget_status: "Sudah disetujui",
    pic_name: "Budi",
    pic_email: "budi@contoh.co.id",
    need_description: "Migrasi data warehouse",
    need_note: null,
    timeline_date: null,
    ...overrides,
  };
}

export function makeQualificationView(overrides: Partial<QualificationView> = {}): QualificationView {
  return {
    legacy: false,
    schema_version: 1,
    answers: makeAnswers(),
    sub_scores: null,
    feedback: null,
    legacy_data: null,
    ...overrides,
  };
}

/** Respons GET /projects/{id} untuk halaman edit. */
export function makeProjectDetail(overrides: Record<string, unknown> = {}) {
  return {
    id_project: "22222222-2222-4222-8222-222222222222",
    project_name: "Migrasi DWH",
    customer_name: "PT Contoh",
    status: "Need Clarification",
    dq_number: "DQ-2025-001",
    target_submit: "2025-12-31",
    bant_detail: null,
    sales_pic: { id: "00000000-0000-4000-8000-000000000001" },
    qualification: makeQualificationView(),
    ...overrides,
  };
}

/** Proyek legacy (dibuat sebelum kuesioner): hanya metadata BANT lama. */
export function makeLegacyProjectDetail(overrides: Record<string, unknown> = {}) {
  return makeProjectDetail({
    status: "Pending Assignment",
    bant_detail: {
      budget_mrr: 25000000,
      pic_name: "Siti",
      pic_position: "CTO",
      pic_email: "siti@contoh.co.id",
      need_description: "Kebutuhan lama",
    },
    qualification: makeQualificationView({
      legacy: true,
      answers: null,
      legacy_data: { budget_mrr: 25000000, pic_name: "Siti", pic_position: "CTO", pic_email: "siti@contoh.co.id", need_description: "Kebutuhan lama" },
    }),
    ...overrides,
  });
}
