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

import { ApiError } from "../fetcher";

// Base URL API backend
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "/api/v1";

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
}

/** Input untuk membuat dokumen baru */
export interface CreateDocumentInput {
  doc_type: DocType;
  gdrive_link: string;
  folder_type: FolderType;
  notes?: string;
}

/**
 * Helper untuk mendapatkan auth token
 */
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/documents`,
    { headers }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengambil daftar dokumen (status ${response.status})`,
      response.status,
      errorData
    );
  }

  // Backend mengembalikan { documents: [...], total } di dalam `data`
  const json = await response.json();
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/documents`,
    {
      method: "POST",
      headers,
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal membuat dokumen (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/documents/${docId}/status`,
    {
      method: "PATCH",
      headers,
      body: JSON.stringify({ new_status: newStatus }),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengubah status dokumen (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/dq-number`,
    {
      method: "PATCH",
      headers,
      body: JSON.stringify({ dq_number: dqNumber }),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal menyimpan DQ Number (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/documents/solutions`,
    { headers }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengambil dokumen Solutions (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}
