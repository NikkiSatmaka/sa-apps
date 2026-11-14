/** Fixture grup shell + dashboard (tiket #69): bentuk sama dengan respons backend. */
import type { AvailableSA, PendingProject } from "@/lib/api/assignment";

export interface StatusCountItem {
  status: string;
  count: number;
}

export function makeStatusSummary(): StatusCountItem[] {
  return [
    { status: "Assigned", count: 3 },
    { status: "Ready", count: 2 },
  ];
}

/** Item GET /projects untuk dashboard Sales (field tambahan SLA opsional). */
export function makeSalesProject(overrides: Record<string, unknown> = {}) {
  return {
    id_project: "11111111-1111-4111-8111-111111111111",
    project_name: "Proyek Sales Contoh",
    customer_name: "PT Contoh",
    status: "Assigned",
    dq_number: null,
    bant_score: 72,
    sla_days_elapsed: null,
    sla_is_locked: false,
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Item GET /projects?assigned_to=me untuk dashboard SA (ada hitungan dokumen). */
export function makeSAProject(overrides: Record<string, unknown> = {}) {
  return {
    id_project: "22222222-2222-4222-8222-222222222222",
    project_name: "Proyek SA Contoh",
    customer_name: "PT Pelanggan",
    status: "Assigned",
    dq_number: "DQ-001",
    updated_at: "2025-02-01T00:00:00Z",
    doc_final_count: 1,
    doc_total_count: 4,
    sla_days_elapsed: null,
    sla_is_locked: false,
    ...overrides,
  };
}

export function makePendingProject(overrides: Partial<PendingProject> = {}): PendingProject {
  return {
    id_project: "33333333-3333-4333-8333-333333333333",
    project_name: "Proyek Antrian",
    customer_name: "PT Antrian",
    bant_score: 80,
    use_case_tags: ["Cloud", "AI"],
    status: "Pending Assignment",
    target_submit: "2025-12-31",
    gdrive_folder_id: null,
    folder_provisioning_status: "provisioned",
    created_at: "2025-01-01T00:00:00Z",
    sales_pic: { id: "00000000-0000-4000-8000-000000000001", name: "Sales Demo", email: "sales@example.com" },
    ...overrides,
  };
}

export function makeAvailableSA(overrides: Partial<AvailableSA> = {}): AvailableSA {
  return {
    id: "00000000-0000-4000-8000-000000000002",
    name: "SA Demo",
    email: "sa@example.com",
    avatar_url: null,
    active_project_count: 1,
    role: "SA",
    ...overrides,
  };
}

/** GET /sa/utilization (jam per bulan per SA). */
export function makeMonthlyUtilization(overrides: Record<string, unknown> = {}) {
  return {
    year: 2025,
    monthly_data: [
      {
        sa_id: "00000000-0000-4000-8000-000000000002",
        sa_name: "SA Demo",
        months: { "1": 5, "2": 20, "3": 45, "4": 80 },
        total_hours: 150,
      },
    ],
    summary: { months: { "1": 5, "2": 20, "3": 45, "4": 80 }, total_hours: 150, sa_count: 1 },
    ...overrides,
  };
}

/** GET /utilization/summary (komposisi Project vs Non-Project + fase). */
export function makeUtilizationSummary(overrides: Record<string, unknown> = {}) {
  return {
    year: 2025,
    work_type: {
      months: { "1": { Project: 8, "Non-Project": 2 }, "2": { Project: 0, "Non-Project": 0 } },
      totals: { Project: 8, "Non-Project": 2 },
      grand_total: 10,
    },
    project_phase: {
      totals: { "Pre-Implementation": 4, Implementation: 4 },
      total: 8,
    },
    ...overrides,
  };
}

/** GET /utilization/projects (effort per proyek). */
export function makeProjectUtilization() {
  return [
    {
      id_project: "44444444-4444-4444-8444-444444444444",
      project_name: "Proyek Effort",
      customer_name: "PT Effort",
      status: "Ready",
      total_hours: 12,
      sa_personnel: [{ sa_id: "00000000-0000-4000-8000-000000000002", sa_name: "SA Demo", hours: 12 }],
    },
  ];
}

/** GET /admin/users. */
export function makeAdminUsers() {
  return [
    { id: "00000000-0000-4000-8000-000000000001", name: "Sales Demo", email: "sales@example.com", role: "Sales", is_admin: false },
    { id: "00000000-0000-4000-8000-000000000005", name: "Product Demo", email: "product@example.com", role: "Product", is_admin: false },
    { id: "00000000-0000-4000-8000-000000000004", name: "Admin Demo", email: "admin@example.com", role: "SA", is_admin: true },
  ];
}
