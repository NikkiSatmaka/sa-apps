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

/** Status kesiapan handover */
export interface HandoverStatus {
  is_ready: boolean;
  has_hld_final: boolean;
  is_closed_win: boolean;
  pmo_email: string | null;
  delivery_email: string | null;
}

/** Response setelah trigger handover */
export interface HandoverResult {
  status: string;
  message: string;
  handover_folder_id?: string;
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
 * @returns Hasil handover (status + message)
 */
export async function triggerHandover(
  projectId: string
): Promise<HandoverResult> {
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
 * @returns Status kesiapan (HLD final? Closed-Win? Email configured?)
 */
export async function getHandoverStatus(
  projectId: string
): Promise<HandoverStatus> {
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
 * @returns Konfirmasi sukses
 */
export async function setHandoverConfig(
  projectId: string,
  pmoEmail: string,
  deliveryEmail: string
): Promise<{ message: string }> {
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
      }),
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
