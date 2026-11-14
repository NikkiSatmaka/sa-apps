/**
 * API Client untuk modul Notifications
 *
 * Fungsi-fungsi untuk komunikasi dengan backend:
 * - getNotifications: Ambil riwayat notifikasi (paginated)
 * - markAsRead: Tandai notifikasi sebagai dibaca
 * - getUnreadCount: Ambil jumlah notifikasi belum dibaca
 *
 * Requirements: 14.7, 14.8
 */

import { apiCall } from "../fetcher";

/** Tipe notifikasi event */
export type NotificationEventType =
  | "assignment"
  | "status_change"
  | "sla_reminder"
  | "sla_escalation"
  | "handover"
  | "doc_ready"
  | "komentar";

/** Tipe data notifikasi dari backend */
export interface Notification {
  id: string;
  event_type: NotificationEventType;
  recipient_user_id: string;
  channel: "in-app" | "email";
  status: "pending" | "sent" | "failed" | "read";
  reference_id: string | null;
  metadata: Record<string, unknown> | null;
  message: string;
  created_at: string;
  read_at: string | null;
}

/** Response paginated notifikasi */
export interface PaginatedNotifications {
  items: Notification[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/** Response unread count */
export interface UnreadCountResponse {
  count: number;
}

/**
 * Ambil riwayat notifikasi user (paginated, 20/page)
 *
 * @param page - Nomor halaman (1-based)
 * @returns Paginated notifications
 */
export async function getNotifications(
  page: number = 1
): Promise<PaginatedNotifications> {
  const json = await apiCall(`/notifications?page=${page}&per_page=20`, {
    pesanGagal: "Gagal mengambil notifikasi",
  });
  return json.data ?? json;
}

/**
 * Tandai notifikasi sebagai dibaca
 *
 * @param notificationId - ID notifikasi
 */
export async function markAsRead(notificationId: string): Promise<void> {
  await apiCall(`/notifications/${notificationId}/read`, {
    method: "PATCH",
    pesanGagal: "Gagal menandai notifikasi",
    tanpaBody: true,
  });
}

/**
 * Ambil jumlah notifikasi yang belum dibaca
 *
 * @returns Objek dengan field count
 */
export async function getUnreadCount(): Promise<UnreadCountResponse> {
  const json = await apiCall("/notifications/unread-count", {
    pesanGagal: "Gagal mengambil unread count",
  });
  return json.data ?? json;
}
