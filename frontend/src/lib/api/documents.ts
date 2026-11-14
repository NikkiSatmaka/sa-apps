/**
 * API Client untuk modul Documents
 *
 * Fungsi-fungsi untuk komunikasi dengan backend:
 * - getProjectDocuments: Ambil daftar dokumen per proyek
 * - createDocument: Buat entry dokumen baru
 * - updateDocumentStatus: Ubah status dokumen
 * - updateDQNumber: Input/update DQ Number pada proyek
 * - getSolutionsDocuments: Ambil dokumen Solutions dengan gating DQ
 */

import { apiCall } from "../fetcher";

/** Tipe dokumen yang didukung */
export type DocType = "Requirement" | "PropTek" | "BOQ" | "Mandays" | "MoM" | "RFP" | "HLD";

/** Tipe folder GDrive */
export type FolderType = "Inventory" | "Diagram" | "Solutions";

/** Status dokumen */
export type DocStatus = "Draft" | "Reviewed" | "Final";

/** Kategori butir Requirement (himpunan tetap, selaras kontrak backend) */
export type RequirementKategori =
  | "Fungsional"
  | "Teknis"
  | "Kepatuhan"
  | "Integrasi"
  | "Timeline"
  | "Asumsi";

/** Satu butir Requirement turunan AI */
export interface RequirementItem {
  id: string;
  kategori: RequirementKategori;
  butir: string;
}

/** Interface dokumen dari backend */
export interface Document {
  id_doc: string;
  id_project: string;
  doc_type: DocType;
  status: DocStatus;
  /** Kosong hanya untuk Requirement (konten turunan AI, tanpa file Drive) */
  gdrive_link: string | null;
  folder_type: FolderType;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** Kosong untuk Requirement hasil generate sistem */
  created_by: string | null;
  updated_by: string | null;
  /** Hanya Requirement: daftar butir; null untuk dokumen lain */
  content: RequirementItem[] | null;
  is_overridden: boolean;
  source_hash: string | null;
  generated_at: string | null;
  source_truncated: boolean;
  /** Requirement di-override/Final dan sumbernya berubah → tampilkan banner (#37) */
  source_changed?: boolean;
}

/** Input untuk membuat dokumen baru */
export interface CreateDocumentInput {
  doc_type: DocType;
  gdrive_link: string;
  folder_type: FolderType;
  notes?: string;
}

/**
 * Ambil daftar dokumen untuk proyek tertentu
 *
 * @param projectId - ID proyek
 * @returns Array dokumen
 */
export async function getProjectDocuments(
  projectId: string
): Promise<Document[]> {
  // Backend mengembalikan { documents: [...], total } di dalam `data`
  const json = await apiCall(`/projects/${projectId}/documents`, {
    pesanGagal: "Gagal mengambil daftar dokumen",
  });
  return json.data?.documents ?? [];
}

/**
 * Buat entry dokumen baru pada proyek
 *
 * @param projectId - ID proyek
 * @param data - Data dokumen baru
 * @returns Dokumen yang dibuat
 */
export async function createDocument(
  projectId: string,
  data: CreateDocumentInput
): Promise<Document> {
  const json = await apiCall(`/projects/${projectId}/documents`, {
    method: "POST",
    body: data,
    pesanGagal: "Gagal membuat dokumen",
  });
  return json.data ?? json;
}

/**
 * Update status dokumen
 * Transisi valid: Draft → Reviewed → Final
 *
 * @param docId - ID dokumen
 * @param newStatus - Status baru
 * @returns Dokumen yang diperbarui
 */
export async function updateDocumentStatus(
  docId: string,
  newStatus: DocStatus
): Promise<Document> {
  const json = await apiCall(`/documents/${docId}/status`, {
    method: "PATCH",
    body: { new_status: newStatus },
    pesanGagal: "Gagal mengubah status dokumen",
  });
  return json.data ?? json;
}

/**
 * Input atau update DQ Number pada proyek
 *
 * @param projectId - ID proyek
 * @param dqNumber - Nilai DQ Number (alfanumerik + hyphen, 5-20 karakter)
 * @returns Data proyek yang diperbarui
 */
export async function updateDQNumber(
  projectId: string,
  dqNumber: string
): Promise<{ id_project: string; dq_number: string; status: string }> {
  const json = await apiCall(`/projects/${projectId}/dq-number`, {
    method: "PATCH",
    body: { dq_number: dqNumber },
    pesanGagal: "Gagal menyimpan DQ Number",
  });
  return json.data ?? json;
}

/**
 * Ambil dokumen Solutions dengan gating DQ Number
 * Jika DQ belum diinput, link dokumen Solutions disembunyikan
 *
 * @param projectId - ID proyek
 * @returns Array dokumen Solutions (link mungkin null jika DQ belum ada)
 */
export async function getSolutionsDocuments(
  projectId: string
): Promise<Document[]> {
  const json = await apiCall(`/projects/${projectId}/documents/solutions`, {
    pesanGagal: "Gagal mengambil dokumen Solutions",
  });
  return json.data ?? json;
}

/** Status generate Requirement di level proyek (#34) */
export type RequirementGenerationStatus = "pending" | "ready" | "failed" | null;

export interface RequirementStatusInfo {
  requirement_generation_status: RequirementGenerationStatus;
  can_regenerate_requirement: boolean;
}

/** Ambil status generate Requirement + hak generate ulang untuk pengguna saat ini */
export async function getRequirementStatus(
  projectId: string
): Promise<RequirementStatusInfo> {
  const json = await apiCall(`/projects/${projectId}/documents`, {
    pesanGagal: "Gagal mengambil status Requirement",
  });
  return {
    requirement_generation_status:
      json.data?.requirement_generation_status ?? null,
    can_regenerate_requirement: Boolean(json.data?.can_regenerate_requirement),
  };
}

/** Generate ulang Requirement (juga dipakai sebagai "coba lagi") */
export async function regenerateRequirement(projectId: string): Promise<void> {
  await apiCall(`/projects/${projectId}/requirement/regenerate`, {
    method: "POST",
    pesanGagal: "Gagal memulai generate ulang",
    ambilPesan: (d) => d?.detail as string | undefined,
    tanpaBody: true,
  });
}

/** Isi butir yang dikirim saat menambah/mengubah butir Requirement */
export interface RequirementItemInput {
  kategori: RequirementKategori;
  butir: string;
}

/** Request ke endpoint override butir Requirement (#36); mengembalikan dokumen terbaru */
async function requirementItemRequest(
  method: "POST" | "PUT" | "DELETE",
  projectId: string,
  itemId: string | null,
  body?: RequirementItemInput
): Promise<Document> {
  const suffix = itemId ? `/${itemId}` : "";
  const json = await apiCall(`/projects/${projectId}/requirement/items${suffix}`, {
    method,
    body: body ?? undefined,
    pesanGagal: "Gagal menyimpan butir Requirement",
    ambilPesan: (d) => (d?.message as string | undefined) || (d?.detail as { toString(): string } | undefined)?.toString(),
  });
  return json.data ?? json;
}

/** Tambah butir Requirement (menyetel is_overridden) */
export function addRequirementItem(
  projectId: string,
  input: RequirementItemInput
): Promise<Document> {
  return requirementItemRequest("POST", projectId, null, input);
}

/** Ubah kategori/teks satu butir Requirement */
export function updateRequirementItem(
  projectId: string,
  itemId: string,
  input: RequirementItemInput
): Promise<Document> {
  return requirementItemRequest("PUT", projectId, itemId, input);
}

/** Hapus satu butir Requirement */
export function deleteRequirementItem(
  projectId: string,
  itemId: string
): Promise<Document> {
  return requirementItemRequest("DELETE", projectId, itemId);
}

/** "Pertahankan versi saya": perbarui hash sumber tanpa mengubah konten Requirement (#37) */
export async function keepRequirementVersion(projectId: string): Promise<void> {
  await apiCall(`/projects/${projectId}/requirement/keep-version`, {
    method: "POST",
    pesanGagal: "Gagal mempertahankan versi Requirement",
    ambilPesan: (d) => d?.detail as string | undefined,
    tanpaBody: true,
  });
}
