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

import { apiCall } from "../fetcher";

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
 * Ambil rekomendasi dokumen serupa berdasarkan use_case_tags proyek
 * Endpoint: GET /api/v1/projects/{id}/recommendations
 *
 * @param projectId - ID proyek yang sedang dikerjakan
 * @returns Array rekomendasi (max 5 item), diurutkan by match_count descending
 */
export async function getRecommendations(
  projectId: string
): Promise<Recommendation[]> {
  const json = await apiCall(`/projects/${projectId}/recommendations`, {
    pesanGagal: "Gagal mengambil rekomendasi",
  });
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
  const json = await apiCall(`/projects/${projectId}/handover`, {
    method: "POST",
    pesanGagal: "Gagal memproses handover",
  });
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
  const json = await apiCall(`/projects/${projectId}/handover-status`, {
    pesanGagal: "Gagal mengecek status handover",
  });
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
  const json = await apiCall(`/projects/${projectId}/handover-config`, {
    method: "POST",
    body: {
      pmo_email: pmoEmail,
      delivery_email: deliveryEmail,
    } satisfies HandoverConfigInput,
    pesanGagal: "Gagal menyimpan konfigurasi handover",
  });
  return json.data ?? json;
}
