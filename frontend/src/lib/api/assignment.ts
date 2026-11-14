/**
 * API Client untuk modul Assignment (Lead_SA)
 *
 * Fungsi-fungsi untuk:
 * - getPendingAssignment: Ambil daftar proyek menunggu assignment
 * - getAvailableSA: Ambil daftar SA tersedia + workload
 * - assignProject: Assign SA ke proyek
 */

import { fetcher, apiRequest } from "../fetcher";

// === Tipe Data ===

/** Proyek yang menunggu assignment */
export interface PendingProject {
  id_project: string;
  project_name: string;
  customer_name: string;
  bant_score: number;
  use_case_tags: string[];
  status: string;
  target_submit: string;
  gdrive_folder_id: string | null;
  folder_provisioning_status: "pending" | "provisioned" | "failed" | null;
  created_at: string;
  sales_pic: {
    id: string;
    name: string;
    email: string;
  };
}

/** SA yang tersedia untuk assignment */
export interface AvailableSA {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  active_project_count: number;
  /** Peran kandidat ("SA" atau "Lead_SA"); dipakai menyaring dropdown Lead SA. */
  role: "SA" | "Lead_SA";
}

/** Response setelah assignment berhasil */
export interface AssignmentResponse {
  id_project: string;
  assigned_sa: string;
  assigned_at: string;
  status: string;
}

/** Ringkasan proyek per status (untuk overview) */
export interface ProjectStatusSummary {
  status: string;
  count: number;
}

// === API Functions ===

/**
 * Ambil daftar proyek berstatus "Awaiting Assignment"
 * Digunakan di dashboard Lead_SA untuk antrian assignment
 */
export async function getPendingAssignment(): Promise<PendingProject[]> {
  return fetcher<PendingProject[]>("/projects/pending-assignment");
}

/**
 * Ambil daftar SA yang tersedia beserta jumlah proyek aktif
 * Digunakan di modal assignment untuk memilih SA
 */
export async function getAvailableSA(): Promise<AvailableSA[]> {
  return fetcher<AvailableSA[]>("/sa/available");
}

/**
 * Assign SA ke proyek tertentu
 * Hanya bisa dilakukan oleh Lead_SA
 *
 * @param projectId - ID proyek yang akan di-assign
 * @param saId - ID SA yang ditugaskan
 * @param leadSaId - ID Lead SA proyek (wajib bila yang meng-assign bukan Lead_SA)
 * @returns Data assignment yang berhasil
 */
export async function assignProject(
  projectId: string,
  saId: string,
  leadSaId?: string
): Promise<AssignmentResponse> {
  return apiRequest<AssignmentResponse>(`/projects/${projectId}/assign`, {
    method: "POST",
    body: leadSaId ? { sa_id: saId, lead_sa_id: leadSaId } : { sa_id: saId },
  });
}

/**
 * Reassign (ubah) SA yang ditugaskan pada proyek
 * Hanya bisa dilakukan oleh Lead_SA / Admin
 *
 * @param projectId - ID proyek yang akan di-reassign
 * @param saId - ID SA baru
 * @param leadSaId - hanya dikirim bila proyek belum punya lead_sa (yang sudah ada tidak ditimpa)
 * @returns Data reassignment yang berhasil
 */
export async function reassignProject(
  projectId: string,
  saId: string,
  leadSaId?: string
): Promise<{ id_project: string; assigned_sa: string; assigned_sa_name: string; status: string }> {
  return apiRequest(`/projects/${projectId}/reassign`, {
    method: "POST",
    body: leadSaId ? { sa_id: saId, lead_sa_id: leadSaId } : { sa_id: saId },
  });
}

/**
 * Provision ulang folder Google Drive untuk proyek yang provisioning-nya gagal
 * Hanya bisa dilakukan oleh Lead_SA / Admin (role-guard di backend)
 *
 * @param projectId - ID proyek yang folder-nya akan di-provision ulang
 * @returns Data status provisioning setelah dijadwalkan
 */
export async function reprovisionFolder(
  projectId: string
): Promise<{
  id_project: string;
  folder_provisioning_status: string;
  folder_provisioning_triggered: boolean;
}> {
  return apiRequest(`/projects/${projectId}/provision-folder`, {
    method: "POST",
  });
}
