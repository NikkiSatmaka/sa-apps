import type { Document, RequirementItem } from "@/lib/api/documents";
import { makeDocument } from "./documents";

/** Butir Requirement (bentuk `RequirementItem` backend). */
export function makeRequirementItem(overrides: Partial<RequirementItem> = {}): RequirementItem {
  return {
    id: "item-1",
    kategori: "Fungsional",
    butir: "Sistem menyediakan login SSO",
    ...overrides,
  };
}

/** Dokumen Requirement: tanpa link Drive, konten berisi butir, dibuat sistem (created_by null). */
export function makeRequirementDoc(overrides: Partial<Document> = {}): Document {
  return makeDocument({
    id_doc: "33333333-3333-4333-8333-333333333333",
    doc_type: "Requirement",
    folder_type: "Inventory",
    gdrive_link: null,
    content: [
      makeRequirementItem({ id: "i-1", kategori: "Fungsional", butir: "Sistem menyediakan login SSO" }),
      makeRequirementItem({ id: "i-2", kategori: "Teknis", butir: "Deploy di Kubernetes" }),
      makeRequirementItem({ id: "i-3", kategori: "Fungsional", butir: "Ekspor laporan PDF" }),
    ],
    ...overrides,
  });
}

/** Isi `data` GET /projects/:id/documents (daftar + status generate Requirement). */
export function makeDocumentsData(
  documents: Document[],
  extra: {
    requirement_generation_status?: "pending" | "ready" | "failed" | null;
    can_regenerate_requirement?: boolean;
  } = {}
) {
  return {
    documents,
    total: documents.length,
    requirement_generation_status: null,
    can_regenerate_requirement: false,
    ...extra,
  };
}
