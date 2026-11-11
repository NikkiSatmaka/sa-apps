import type { Notification, PaginatedNotifications } from "@/lib/api/notifications";

export function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    event_type: "assignment",
    recipient_user_id: "00000000-0000-4000-8000-000000000002",
    channel: "in-app",
    status: "sent",
    reference_id: "11111111-1111-4111-8111-111111111111",
    metadata: null,
    message: "Anda ditugaskan ke proyek baru",
    created_at: "2025-01-01T00:00:00Z",
    read_at: null,
    ...overrides,
  };
}

export function makePaginatedNotifications(items: Notification[] = [makeNotification()]): PaginatedNotifications {
  return { items, total: items.length, page: 1, per_page: 20, total_pages: 1 };
}
