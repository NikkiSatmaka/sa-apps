/**
 * API Client untuk modul Projects
 *
 * Fungsi-fungsi untuk komunikasi dengan backend:
 * - createProject: Submit proyek baru (multipart/form-data)
 * - getBANTResult: Ambil hasil scoring BANT
 */

import { apiCall, apiRequest } from "../fetcher";
import { toPayload, type QualificationAnswers, type QualificationSchema } from "../qualification";

/** Tipe response BANT Result dari backend */
export interface BANTResult {
  bant_score: number;
  bant_detail: {
    budget: number;
    authority: number;
    need: number;
    timeline: number;
  };
  use_case_tags: string[];
  status: string;
  feedback?: string | null;
}

/** Sub-skor BANT per kriteria (0-25) */
export interface BANTSubScores {
  budget: number;
  authority: number;
  need: number;
  timeline: number;
}

/** Tipe response setelah project dibuat (skor dihitung backend dari kuesioner) */
export interface CreateProjectResponse {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  /** null bila menunggu analisis file */
  bant_score: number | null;
  sub_scores: BANTSubScores | null;
  feedback: string | null;
  scoring_triggered: boolean;
}

/** Error validasi per field dari backend (422) */
export interface FieldError {
  field: string;
  reason: string;
}

/** Ambil daftar error per field dari ApiError 422 (format `{data: [{field, reason}]}`) */
export function extractFieldErrors(err: unknown): FieldError[] {
  const data = (err as { data?: { data?: unknown } } | null)?.data?.data;
  if (!Array.isArray(data)) return [];
  return data.filter(
    (e): e is FieldError =>
      typeof e?.field === "string" && typeof e?.reason === "string"
  );
}

/**
 * Submit proyek baru dengan file attachment
 * Menggunakan multipart/form-data karena ada file upload
 *
 * @param data - Form data berisi field proyek dan files
 * @returns Response berisi data proyek yang dibuat
 */
export async function createProject(
  data: FormData
): Promise<CreateProjectResponse> {
  // FormData: apiCall tidak men-set Content-Type (boundary dari browser)
  const json = await apiCall("/projects", {
    method: "POST",
    body: data,
    pesanGagal: "Gagal membuat proyek",
  });
  return json.data ?? json;
}

/**
 * Ambil hasil BANT scoring untuk proyek tertentu
 *
 * @param projectId - ID proyek
 * @returns Hasil BANT atau null jika belum tersedia
 */
export async function getBANTResult(
  projectId: string
): Promise<BANTResult | null> {
  // 404 berarti belum ada hasil
  const json = await apiCall(`/projects/${projectId}/bant-result`, {
    pesanGagal: "Gagal mengambil hasil BANT",
    terimaStatus: [404],
  });
  if (json === null) return null;
  return json.data ?? json;
}

/** Hasil simpan jawaban kuesioner: re-score (total_score, status, feedback) atau koreksi (rescored=false). */
export interface UpdateAnswersResult {
  total_score: number | null;
  status: string;
  feedback?: string | null;
  rescored?: boolean;
}

/** Edit jawaban kuesioner (PUT /projects/{id}/qualification-answers); skor dihitung backend. */
export function updateQualificationAnswers(
  projectId: string,
  schema: QualificationSchema,
  answers: QualificationAnswers
): Promise<UpdateAnswersResult> {
  return apiRequest<UpdateAnswersResult>(`/projects/${projectId}/qualification-answers`, {
    method: "PUT",
    body: toPayload(schema, answers),
  });
}
