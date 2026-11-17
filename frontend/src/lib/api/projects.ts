/**
 * API Client untuk modul Projects
 *
 * Fungsi-fungsi untuk komunikasi dengan backend:
 * - createProject: Submit proyek baru (multipart/form-data)
 * - getBANTResult: Ambil hasil scoring BANT
 */

import { apiCall, apiRequest, fetcher } from "../fetcher";
import { toPayload, type QualificationAnswers, type QualificationSchema } from "../qualification";

export const PROJECT_LIST_PAGE_SIZE = 20;
export const PROJECT_LIST_MAX_PAGE_SIZE = 100;

export interface ProjectListPerson {
  id: string;
  name: string | null;
  email: string | null;
}

export interface ProjectListItem {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  qualification_state?: string | null;
  dq_number: string | null;
  bant_score: number | null;
  use_case_tags: string[];
  estimasi_nilai?: string | null;
  target_submit: string | null;
  assigned_sa?: string | null;
  created_by?: ProjectListPerson | null;
  product_pic?: ProjectListPerson | null;
  sales_pic?: ProjectListPerson | null;
  gdrive_folder_id?: string | null;
  folder_provisioning_status?: string | null;
  created_at?: string | null;
  updated_at: string | null;
  sla_days_elapsed?: number | null;
  sla_is_locked?: boolean;
  doc_final_count?: number;
  doc_total_count?: number;
}

export interface ProjectListPage<T = ProjectListItem> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface IntegrationOperationAttempt {
  attempt: number;
  status: "pending" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  outcome: string | null;
  actionable_error: string | null;
}

export interface IntegrationOperationResponse {
  id: string;
  operation_type: string;
  action: string;
  status: "pending" | "succeeded" | "failed";
  attempts: IntegrationOperationAttempt[];
  started_at: string | null;
  finished_at: string | null;
  outcome: string | null;
  actionable_error: string | null;
  retryable: boolean;
  project_id?: string | null;
  context: Record<string, unknown>;
}

export interface ProjectListParams {
  page: number;
  pageSize?: number;
  involved?: "me";
  status?: string;
  search?: string;
  sort?: string;
}

export function projectListUrl({
  page,
  pageSize = PROJECT_LIST_PAGE_SIZE,
  involved,
  status,
  search,
  sort = "-updated_at",
}: ProjectListParams): string {
  const params = new URLSearchParams();
  if (involved) params.set("involved", involved);
  if (status) params.set("status", status);
  const query = search?.trim();
  if (query) params.set("search", query);
  params.set("sort", sort);
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  return `/projects?${params.toString()}`;
}

export async function getAllProjects(): Promise<ProjectListItem[]> {
  const pageSize = PROJECT_LIST_MAX_PAGE_SIZE;
  const firstPage = await fetcher<ProjectListPage>(
    projectListUrl({ page: 1, pageSize }),
  );
  const projects = [...firstPage.items];
  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const nextPage = await fetcher<ProjectListPage>(
      projectListUrl({ page, pageSize }),
    );
    projects.push(...nextPage.items);
  }
  return projects;
}

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

/** Per-file processing result returned by POST /projects. */
export interface ProjectFileResult {
  filename: string;
  success: boolean;
  error?: string | null;
  size_bytes?: number | null;
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
  files: ProjectFileResult[];
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
