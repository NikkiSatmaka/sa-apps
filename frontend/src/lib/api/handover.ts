/**
 * API Client untuk modul Handover dan RAG Recommendation
 *
 * Fungsi-fungsi untuk komunikasi dengan backend:
 * - getRecommendations: Ambil rekomendasi dokumen serupa (RAG)
 * - triggerHandover: Mulai proses handover ke PMO/Delivery
 * - getHandoverStatus: Cek kesiapan handover
 * - setHandoverConfig: Simpan konfigurasi email PMO/Delivery Lead
 *
 * Requirements: 15.1, 15.3, 15.4, 17.1, 17.6
 */

import { ApiError } from "../fetcher";

// Base URL API backend
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "/api/v1";

/** Satu item rekomendasi dokumen dari RAG */
export interface Recommendation {
  id_project: string;
  project_name: string;
  doc_type: string;
  use_case_tags: string[];
  gdrive_link: string | null;
  match_count: number;
}

/**
 * Kesiapan handover. Sama dengan `HandoverReadiness` di `backend/app/schemas/handover.py`
 * (respons `GET /projects/{id}/handover-status`).
 */
export interface HandoverReadiness {
  ready: boolean;
  /** Prasyarat yang belum terpenuhi (kosong bila `ready`). */
  missing_items: string[];
  pmo_email: string | null;
  delivery_email: string | null;
  project_status: string | null;
  /** Status dokumen HLD; `null` bila belum ada HLD. */
  hld_status: string | null;
}

/** Input `POST /projects/{id}/handover-config` (`HandoverConfigInput` backend). */
export interface HandoverConfigInput {
  pmo_email: string;
  delivery_email: string;
}

/** Respons `POST /projects/{id}/handover-config` (data proyek yang dikonfigurasi). */
export interface HandoverConfigResponse {
  id_project: string;
  project_name: string;
  pmo_lead_email: string;
  delivery_lead_email: string;
}

/** Respons `POST /projects/{id}/handover` (`HandoverResponse` backend). */
export interface HandoverResponse {
  id_project: string;
  project_name: string;
  customer_name: string;
  old_status: string;
  new_status: string;
  pmo_email: string;
  delivery_email: string;
  final_deliverables_folder_id: string | null;
  /** Tipe dokumen berstatus Final yang di-handover. */
  documents_handed_over: string[];
  /** Waktu handover (ISO 8601). */
  handover_at: string;
}

/**
 * Helper untuk mendapatkan auth token
 */
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

/**
 * Ambil rekomendasi dokumen serupa berdasarkan use_case_tags proyek
 * Endpoint: GET /api/v1/projects/{id}/recommendations
 *
 * @param projectId - ID proyek yang sedang dikerjakan
 * @returns Array rekomendasi (max 5 item), diurutkan by match_count descending
 */
export async function getRecommendations(
  projectId: string
): Promise<Recommendation[]> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/recommendations`,
    { headers }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengambil rekomendasi (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/**
 * Trigger proses handover ke PMO/Delivery
 * Endpoint: POST /api/v1/projects/{id}/handover
 *
 * @param projectId - ID proyek yang akan di-handover
 * @returns Hasil handover (`HandoverResponse`)
 */
export async function triggerHandover(
  projectId: string
): Promise<HandoverResponse> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/handover`,
    {
      method: "POST",
      headers,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal memproses handover (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/**
 * Cek kesiapan handover untuk proyek tertentu
 * Endpoint: GET /api/v1/projects/{id}/handover-status
 *
 * @param projectId - ID proyek
 * @returns Kesiapan handover (`ready` dan `missing_items`)
 */
export async function getHandoverStatus(
  projectId: string
): Promise<HandoverReadiness> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/handover-status`,
    { headers }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengecek status handover (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/**
 * Simpan konfigurasi email PMO Lead dan Delivery Lead
 * Endpoint: POST /api/v1/projects/{id}/handover-config
 *
 * @param projectId - ID proyek
 * @param pmoEmail - Email PMO Lead
 * @param deliveryEmail - Email Delivery Lead
 * @returns Data proyek yang dikonfigurasi
 */
export async function setHandoverConfig(
  projectId: string,
  pmoEmail: string,
  deliveryEmail: string
): Promise<HandoverConfigResponse> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/projects/${projectId}/handover-config`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        pmo_email: pmoEmail,
        delivery_email: deliveryEmail,
      } satisfies HandoverConfigInput),
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal menyimpan konfigurasi handover (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}
