"use client";

import type React from "react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { fetcher } from "@/lib/fetcher";
import { markAsRead } from "@/lib/api/notifications";
import type {
  Notification,
  NotificationEventType,
  PaginatedNotifications,
} from "@/lib/api/notifications";

/**
 * Halaman Notification Center
 *
 * Fitur:
 * - Daftar notifikasi dengan status read/unread (unread = bold/highlighted)
 * - Info: event type icon, pesan, timestamp relatif
 * - Klik → mark as read + navigasi ke halaman terkait
 * - Pagination: 20 item per halaman, Previous/Next buttons
 * - Empty state: "Tidak ada notifikasi"
 *
 * Requirements: 14.7, 14.8
 */

/**
 * Format timestamp ke waktu relatif ("2 jam lalu", "5 menit lalu", dll.)
 */
function formatRelativeTime(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return "Baru saja";
  if (diffMinutes < 60) return `${diffMinutes} menit lalu`;
  if (diffHours < 24) return `${diffHours} jam lalu`;
  if (diffDays < 7) return `${diffDays} hari lalu`;

  return date.toLocaleDateString("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * Mendapatkan ikon berdasarkan event type
 */
function getEventIcon(eventType: NotificationEventType): React.JSX.Element {
  switch (eventType) {
    case "assignment":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
        </svg>
      );
    case "status_change":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 0l-3 3a1 1 0 001.414 1.414L9 9.414V13a1 1 0 102 0V9.414l1.293 1.293a1 1 0 001.414-1.414z"
            clipRule="evenodd"
          />
        </svg>
      );
    case "sla_reminder":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
            clipRule="evenodd"
          />
        </svg>
      );
    case "sla_escalation":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
            clipRule="evenodd"
          />
        </svg>
      );
    case "handover":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path d="M8 5a1 1 0 100 2h5.586l-1.293 1.293a1 1 0 001.414 1.414l3-3a1 1 0 000-1.414l-3-3a1 1 0 10-1.414 1.414L13.586 5H8zM12 15a1 1 0 100-2H6.414l1.293-1.293a1 1 0 10-1.414-1.414l-3 3a1 1 0 000 1.414l3 3a1 1 0 001.414-1.414L6.414 15H12z" />
        </svg>
      );
    case "doc_ready":
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path
            fillRule="evenodd"
            d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z"
            clipRule="evenodd"
          />
        </svg>
      );
    default:
      return (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z" />
        </svg>
      );
  }
}

/**
 * Warna background ikon berdasarkan event type
 */
function getEventIconBg(eventType: NotificationEventType): string {
  switch (eventType) {
    case "assignment":
      return "bg-blue-100 text-blue-600";
    case "status_change":
      return "bg-green-100 text-green-600";
    case "sla_reminder":
      return "bg-yellow-100 text-yellow-600";
    case "sla_escalation":
      return "bg-red-100 text-red-600";
    case "handover":
      return "bg-purple-100 text-purple-600";
    case "doc_ready":
      return "bg-indigo-100 text-indigo-600";
    case "komentar":
      return "bg-teal-100 text-teal-600";
    default:
      return "bg-neutral-100 text-neutral-600";
  }
}

/**
 * Menentukan URL navigasi berdasarkan notifikasi
 */
function getNavigationUrl(notification: Notification): string {
  const { event_type, reference_id, metadata } = notification;

  // Jika ada reference_id, gunakan untuk navigasi
  if (reference_id) {
    switch (event_type) {
      case "assignment":
      case "status_change":
      case "sla_reminder":
      case "sla_escalation":
      case "komentar":
        return `/projects/${reference_id}`;
      case "doc_ready":
        // Cek metadata untuk document ID
        if (metadata?.document_id) {
          return `/projects/${reference_id}/documents`;
        }
        return `/projects/${reference_id}`;
      case "handover":
        return `/projects/${reference_id}`;
      default:
        return `/projects/${reference_id}`;
    }
  }

  // Fallback ke dashboard
  return "/dashboard";
}

/**
 * Skeleton loader untuk item notifikasi
 */
function NotificationSkeleton() {
  return (
    <div className="flex items-start gap-3 p-4 animate-pulse">
      <div className="w-10 h-10 rounded-full bg-neutral-200 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-neutral-200 rounded w-3/4" />
        <div className="h-3 bg-neutral-200 rounded w-1/4" />
      </div>
    </div>
  );
}

export default function NotificationsPage() {
  const router = useRouter();
  const [currentPage, setCurrentPage] = useState(1);

  // Ambil data notifikasi dengan SWR
  const { data, isLoading, error } = useSWR<PaginatedNotifications>(
    `/notifications?page=${currentPage}&per_page=20`,
    fetcher,
    { revalidateOnFocus: true }
  );

  /**
   * Handler klik notifikasi:
   * 1. Mark as read (jika belum)
   * 2. Navigasi ke halaman terkait
   */
  async function handleNotificationClick(notification: Notification) {
    // Mark as read jika belum dibaca
    if (notification.status !== "read") {
      try {
        await markAsRead(notification.id);
        // Revalidate data notifikasi dan unread count
        mutate(`/notifications?page=${currentPage}&per_page=20`);
        mutate("/notifications/unread-count");
      } catch {
        // Lanjutkan navigasi meskipun mark-as-read gagal
      }
    }

    // Navigasi ke halaman terkait
    const url = getNavigationUrl(notification);
    router.push(url);
  }

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header halaman */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-neutral-900">
          Notification Center
        </h1>
        <p className="text-sm text-neutral-500 mt-1">
          Riwayat notifikasi dan pemberitahuan
        </p>
      </div>

      {/* Daftar notifikasi */}
      <div className="bg-white border border-neutral-200 rounded-lg overflow-hidden">
        {/* Loading state — skeleton */}
        {isLoading && (
          <div className="divide-y divide-neutral-100">
            {Array.from({ length: 5 }).map((_, i) => (
              <NotificationSkeleton key={i} />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <div className="p-8 text-center">
            <p className="text-sm text-red-600">
              Gagal memuat notifikasi. Silakan coba lagi.
            </p>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && data && data.items.length === 0 && (
          <div className="p-8 text-center">
            <svg
              className="w-12 h-12 mx-auto text-neutral-300 mb-3"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
              />
            </svg>
            <p className="text-sm text-neutral-500">Tidak ada notifikasi</p>
          </div>
        )}

        {/* List notifikasi */}
        {!isLoading && !error && data && data.items.length > 0 && (
          <ul className="divide-y divide-neutral-100" role="list">
            {data.items.map((notification) => {
              const isUnread = notification.status !== "read";

              return (
                <li key={notification.id}>
                  <button
                    onClick={() => handleNotificationClick(notification)}
                    className={`w-full flex items-start gap-3 p-4 text-left
                      hover:bg-neutral-50 transition-colors duration-100
                      ${isUnread ? "bg-blue-50/50" : "bg-white"}`}
                    aria-label={`${isUnread ? "Belum dibaca: " : ""}${notification.message}`}
                  >
                    {/* Ikon event type */}
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${getEventIconBg(notification.event_type)}`}
                    >
                      {getEventIcon(notification.event_type)}
                    </div>

                    {/* Konten notifikasi */}
                    <div className="flex-1 min-w-0">
                      <p
                        className={`text-sm leading-5 ${
                          isUnread
                            ? "font-semibold text-neutral-900"
                            : "font-normal text-neutral-700"
                        }`}
                      >
                        {notification.message}
                      </p>
                      <p className="text-xs text-neutral-400 mt-1">
                        {formatRelativeTime(notification.created_at)}
                      </p>
                    </div>

                    {/* Indikator unread (dot biru) */}
                    {isUnread && (
                      <div className="shrink-0 mt-2">
                        <span className="w-2 h-2 bg-blue-500 rounded-full block" />
                      </div>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-neutral-500">
            Halaman {data.page} dari {data.total_pages} ({data.total} notifikasi)
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="px-3 py-1.5 text-sm font-medium rounded-md border border-neutral-200
                         hover:bg-neutral-50 transition-colors duration-100
                         disabled:opacity-50 disabled:cursor-not-allowed
                         min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Halaman sebelumnya"
            >
              Previous
            </button>
            <button
              onClick={() =>
                setCurrentPage((p) => Math.min(data.total_pages, p + 1))
              }
              disabled={currentPage >= data.total_pages}
              className="px-3 py-1.5 text-sm font-medium rounded-md border border-neutral-200
                         hover:bg-neutral-50 transition-colors duration-100
                         disabled:opacity-50 disabled:cursor-not-allowed
                         min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Halaman berikutnya"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
