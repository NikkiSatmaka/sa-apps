import type { Document } from "@/lib/api/documents";

/** Dokumen (bentuk `Document` backend). */
export function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    id_doc: "22222222-2222-4222-8222-222222222222",
    id_project: "11111111-1111-4111-8111-111111111111",
    doc_type: "BOQ",
    status: "Draft",
    gdrive_link: "https://drive.google.com/file/d/abc",
    folder_type: "Solutions",
    notes: null,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    created_by: null,
    updated_by: null,
    content: null,
    is_overridden: false,
    source_hash: null,
    generated_at: null,
    source_truncated: false,
    ...overrides,
  };
}
