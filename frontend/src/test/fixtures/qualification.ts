import type { QualificationSchema, QuestionDef } from "@/lib/qualification";

export function makeQuestion(overrides: Partial<QuestionDef> = {}): QuestionDef {
  return {
    name: "budget_range",
    group: "budget",
    type: "short",
    label: "Berapa kisaran anggaran?",
    short_label: "Anggaran",
    required: true,
    choices: null,
    hint: null,
    placeholder: null,
    max_length: 200,
    min_value: null,
    max_value: null,
    pattern: null,
    row: null,
    row_hint: null,
    display: null,
    show_char_count: false,
    header: false,
    ...overrides,
  };
}

/** Skema kuesioner mini (GET /qualification/schema; envelope-nya diterapkan handler). */
export function makeQualificationSchema(overrides: Partial<QualificationSchema> = {}): QualificationSchema {
  return {
    schema_version: 1,
    groups: [{ key: "budget", title: "Budget" }],
    questions: [makeQuestion()],
    ...overrides,
  };
}
