/**
 * Tipe respons tampilan workload Lead_SA (`GET /workload/*`, issue #127, spec §2.5).
 * Hanya Lead_SA atau Admin yang boleh memanggilnya (backend membalas 403 untuk yang lain).
 */

export interface BebanSA {
  user_id: string;
  name: string;
  email: string;
  role: string;
  project_aktif: number;
  subtask_aktif: number;
  jam_minggu_ini: number;
}

export interface BebanResponse {
  minggu_mulai: string;
  items: BebanSA[];
}

export interface SubtaskJatuhTempo {
  id_subtask: string;
  id_project: string;
  project_name: string;
  title: string;
  status: string;
  assigned_sa: string | null;
  assigned_sa_name: string | null;
  due_date: string;
  /** Negatif bila sudah lewat. */
  hari_lagi: number;
  terlambat: boolean;
}

export interface ProjectJatuhTempo {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  target_submit: string;
  hari_lagi: number;
  terlambat: boolean;
}

export interface JatuhTempoResponse {
  hari_peringatan: number;
  subtask: SubtaskJatuhTempo[];
  project: ProjectJatuhTempo[];
}

export interface ProjectMacet {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  masuk_status_sejak: string;
  hari_di_status: number;
  ambang_hari: number;
  sumber: "audit" | "updated_at";
}

export interface MacetResponse {
  ambang_hari: Record<string, number>;
  items: ProjectMacet[];
}

export type JenisButuhAksi = "awaiting_assignment" | "dq_kosong" | "need_clarification";

export interface ProjectButuhAksi {
  jenis: JenisButuhAksi;
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  qualification_state: string;
}

export interface ButuhAksiResponse {
  items: ProjectButuhAksi[];
}
