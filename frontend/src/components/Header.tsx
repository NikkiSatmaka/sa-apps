"use client";

import { useSidebarStore } from "@/store/sidebar";
import { NotificationBell } from "@/components/NotificationBell";
import { Breadcrumb } from "@/components/Breadcrumb";
import { UserMenu } from "@/components/UserMenu";

/**
 * Header Component — tinggi maksimal 64px (Requirement 19.7)
 *
 * Fitur:
 * - Tombol toggle sidebar (mobile)
 * - Breadcrumb / judul halaman
 * - Notifikasi badge
 * - User menu
 */
export function Header() {
  const { toggle } = useSidebarStore();

  return (
    <header className="flex items-center justify-between h-[64px] max-h-[64px] px-4 md:px-6 bg-white border-b border-neutral-200 shrink-0">
      {/* Kiri: toggle sidebar (mobile) + breadcrumb */}
      <div className="flex items-center gap-3">
        {/* Toggle sidebar untuk mobile */}
        <button
          onClick={toggle}
          className="flex md:hidden items-center justify-center w-[44px] h-[44px] rounded-lg
                     hover:bg-neutral-100 transition-colors duration-100"
          aria-label="Toggle navigasi"
        >
          <svg
            className="w-5 h-5 text-neutral-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>

        <Breadcrumb />
      </div>

      {/* Kanan: notifikasi + user menu */}
      <div className="flex items-center gap-2">
        {/* Tombol notifikasi dengan badge unread count */}
        <NotificationBell />

        {/* User avatar / menu */}
        <UserMenu />
      </div>
    </header>
  );
}
