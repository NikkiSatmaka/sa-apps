/** Fixture grup operasi (assignment, kolaborasi, handover, activity log) — bentuk sama dengan respons backend. */
import type { AvailableSA, PendingProject } from "@/lib/api/assignment";
import type { HandoverReadiness } from "@/lib/api/handover";

export function makeAvailableSA(overrides: Partial<AvailableSA> = {}): AvailableSA {
  return {
    id: "sa-1",
    name: "Budi Santoso",
    email: "budi@example.com",
    avatar_url: null,
    active_project_count: 1,
    role: "SA",
    ...overrides,
  };
}

export function makePendingProject(overrides: Partial<PendingProject> = {}): PendingProject {
  return {
    id_project: "11111111-1111-4111-8111-111111111111",
    project_name: "Migrasi Cloud",
    customer_name: "PT Contoh",
    bant_score: 72,
    use_case_tags: ["Cloud Migration"],
    status: "Awaiting Assignment",
    target_submit: "2025-12-31",
    gdrive_folder_id: null,
    folder_provisioning_status: null,
    created_at: "2025-01-01T00:00:00Z",
    sales_pic: { id: "s1", name: "Sales Demo", email: "sales@example.com" },
    ...overrides,
  };
}

export function makeCollaborator(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    user_id: "u-collab-1",
    user_name: "Citra Dewi",
    user_email: "citra@example.com",
    user_role: "SA",
    role: "viewer" as "viewer" | "contributor",
    added_by_name: "SA Demo",
    created_at: "2025-01-02T00:00:00Z",
    ...overrides,
  };
}

export function makeUserSearchResult(overrides: Record<string, unknown> = {}) {
  return { id: "u-found-1", name: "Dani Pratama", email: "dani@example.com", role: "SA", ...overrides };
}

export function makeActivityLog(overrides: Record<string, unknown> = {}) {
  return {
    id_log: "log-1",
    project_phase: "Pre-Implementation",
    subtask_category: "Assessment",
    duration_hours: 2,
    raw_notes: "Diskusi kebutuhan dengan customer",
    ai_polished_notes: null as null | {
      discussion_points: string[];
      action_items: { description: string; pic?: string | null }[];
    },
    created_at: "2025-03-10T08:00:00Z",
    ...overrides,
  };
}

export function makeStoryPage(items: unknown[] = [makeActivityLog()], overrides: Record<string, unknown> = {}) {
  return { items, total: items.length, page: 1, page_size: 20, total_pages: 1, ...overrides };
}

/** Kesiapan handover (bentuk `HandoverReadiness` backend): siap, email PMO/Delivery terisi. */
export function makeHandoverReadiness(overrides: Partial<HandoverReadiness> = {}): HandoverReadiness {
  return {
    ready: true,
    missing_items: [],
    pmo_email: "pmo@example.com",
    delivery_email: "delivery@example.com",
    project_status: "Won",
    hld_status: "Final",
    ...overrides,
  };
}
