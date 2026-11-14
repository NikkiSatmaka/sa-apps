/** Fixture detail proyek (GET /projects/{id}), Source document, subtask, dan story. */
export const DETAIL_ID = "22222222-2222-4222-8222-222222222222";

export interface SourceDocFixture {
  id: string;
  filename: string;
  doc_type: "MoM" | "RFP";
  size_bytes: number;
  extraction_status: "pending" | "extracted" | "empty" | "failed";
  truncated: boolean;
  text_length: number;
  created_at: string | null;
  updated_at: string | null;
}

export function makeSourceDoc(overrides: Partial<SourceDocFixture> = {}): SourceDocFixture {
  return {
    id: "doc-1",
    filename: "mom.pdf",
    doc_type: "MoM",
    size_bytes: 2048,
    extraction_status: "extracted",
    truncated: false,
    text_length: 1500,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeProjectDetail(overrides: Record<string, unknown> = {}) {
  return {
    id_project: DETAIL_ID,
    project_name: "Migrasi Cloud ACME",
    customer_name: "PT ACME",
    status: "Assigned",
    qualification_state: "Qualified",
    previous_status: null,
    lost_reason: null,
    dq_number: null,
    bant_score: 72,
    bant_detail: { budget: 18, authority: 18, need: 18, timeline: 18 },
    use_case_tags: ["Cloud Migration", "Security"],
    target_submit: "2025-12-31",
    sales_pic: { id: "s1", name: "Sales Demo", email: "sales@example.com" },
    assigned_sa: { id: "sa1", name: "SA Demo", email: "sa@example.com" },
    collaborators: [],
    source_documents: [],
    gdrive_folder_id: null,
    folder_provisioning_status: null,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-02T00:00:00Z",
    ...overrides,
  };
}

export interface SubtaskFixture {
  id_subtask: string;
  id_project: string;
  title: string;
  status: "open" | "in_progress" | "done";
  assigned_sa: string | null;
  assigned_sa_name: string | null;
  created_at: string;
  updated_at: string;
}

export function makeSubtask(overrides: Partial<SubtaskFixture> = {}): SubtaskFixture {
  return {
    id_subtask: "st-1",
    id_project: DETAIL_ID,
    title: "Peer Review HLD",
    status: "open",
    assigned_sa: null,
    assigned_sa_name: null,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeStoryItem(overrides: Record<string, unknown> = {}) {
  return {
    id_log: "log-1",
    subtask_category: "Workshop",
    duration_hours: 2,
    raw_notes: "Diskusi arsitektur",
    ai_polished_notes: null,
    created_at: "2025-01-03T00:00:00Z",
    ...overrides,
  };
}

export interface AnggotaSAFixture {
  id: string;
  name: string;
  email: string;
}

export interface AnggotaSATambahanFixture extends AnggotaSAFixture {
  added_by: string;
  created_at: string;
}

export interface TimSAFixture {
  sa_utama: AnggotaSAFixture | null;
  sa_tambahan: AnggotaSATambahanFixture[];
}

/** Respons `GET /projects/{id}/tim-sa`: SA utama + SA tambahan (ADR 0014). */
export function makeTimSA(overrides: Partial<TimSAFixture> = {}): TimSAFixture {
  return {
    sa_utama: { id: "sa1", name: "SA Demo", email: "sa@example.com" },
    sa_tambahan: [],
    ...overrides,
  };
}

export function makeSATambahan(overrides: Partial<AnggotaSATambahanFixture> = {}): AnggotaSATambahanFixture {
  return {
    id: "sa2",
    name: "Budi Tambahan",
    email: "budi@example.com",
    added_by: "lead1",
    created_at: "2025-01-03T00:00:00Z",
    ...overrides,
  };
}
