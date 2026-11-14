/** Item daftar proyek (GET /projects) — bentuk `ProjectItem` halaman daftar proyek. */
export interface ProjectListItem {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  /** Hanya bermakna saat `status = Intake` (ADR 0013). */
  qualification_state?: string | null;
  dq_number: string | null;
  bant_score: number | null;
  use_case_tags: string[];
  target_submit: string | null;
  updated_at: string | null;
}

export function makeProject(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    id_project: "11111111-1111-4111-8111-111111111111",
    project_name: "Proyek Contoh",
    customer_name: "PT Contoh",
    status: "Intake",
    dq_number: null,
    bant_score: 72,
    use_case_tags: ["Cloud Migration"],
    target_submit: "2025-12-31",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Respons POST /projects (`CreateProjectResponse`). */
export function makeCreateProjectResponse(overrides: Record<string, unknown> = {}) {
  return {
    id_project: "11111111-1111-4111-8111-111111111111",
    project_name: "Proyek Contoh",
    customer_name: "PT Contoh",
    status: "Intake",
    bant_score: 72,
    sub_scores: { budget: 18, authority: 18, need: 18, timeline: 18 },
    feedback: null,
    scoring_triggered: true,
    ...overrides,
  };
}
