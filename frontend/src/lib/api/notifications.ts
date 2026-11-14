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

import { ApiError } from "../fetcher";

// Base URL API backend
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "/api/v1";

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
 * Helper untuk mendapatkan auth token
 */
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
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
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/notifications?page=${page}&per_page=20`,
    { headers }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengambil notifikasi (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/**
 * Tandai notifikasi sebagai dibaca
 *
 * @param notificationId - ID notifikasi
 */
export async function markAsRead(notificationId: string): Promise<void> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE_URL}/notifications/${notificationId}/read`,
    {
      method: "PATCH",
      headers,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal menandai notifikasi (status ${response.status})`,
      response.status,
      errorData
    );
  }
}

/**
 * Ambil jumlah notifikasi yang belum dibaca
 *
 * @returns Objek dengan field count
 */
export async function getUnreadCount(): Promise<UnreadCountResponse> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/notifications/unread-count`, {
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message ||
        `Gagal mengambil unread count (status ${response.status})`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}
