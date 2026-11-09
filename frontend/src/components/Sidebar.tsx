"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSidebarStore } from "@/store/sidebar";
import { useAuthStore } from "@/store/auth";
import { logout } from "@/lib/auth";
import { UserMenu } from "@/components/UserMenu";

/**
 * Sidebar Navigation — collapsible (Requirement 19.7)
 *
 * Lebar:
 * - Terbuka: 240px
 * - Collapsed: 64px
 *
 * Fitur:
 * - Toggle collapse/expand
 * - Navigation links sesuai role user (Bug #6 fix)
 * - Next.js Link component untuk navigasi tanpa full reload (Bug #1 fix)
 * - SVG icons menggantikan emoji (Bug #2 fix)
 * - Touch target min 44x44px (Requirement 12.3)
 */

// --- SVG Icon Components ---

function DashboardIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm10 0a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zm-10 9a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1v-5zm10-2a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1h-4a1 1 0 01-1-1v-7z" />
    </svg>
  );
}

function FolderIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
    </svg>
  );
}

function ActivityLogIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function DocumentIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  );
}

function BellIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
    </svg>
  );
}

function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

// --- Tipe navigasi item ---
interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

// Semua item navigasi yang tersedia
const allNavItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: DashboardIcon },
  { label: "Proyek", href: "/projects", icon: FolderIcon },
  { label: "Activity Log", href: "/activity-logs", icon: ActivityLogIcon },
  { label: "Notifikasi", href: "/notifications", icon: BellIcon },
];

// Item navigasi khusus Admin
const adminNavItems: NavItem[] = [
  { label: "Settings", href: "/admin/settings", icon: SettingsIcon },
];

/**
 * Filter item navigasi berdasarkan role user
 * - Sales: Dashboard, Proyek, Notifikasi
 * - SA: Dashboard, Proyek, Activity Log, Dokumen, Notifikasi
 * - Lead_SA: Dashboard, Proyek, Activity Log, Dokumen, Notifikasi
 * - Admin: Semua + Settings
 */
function getNavItemsForRole(role?: string): NavItem[] {
  switch (role) {
    case "Sales":
      return allNavItems.filter((item) =>
        ["Dashboard", "Proyek", "Notifikasi"].includes(item.label)
      );
    case "SA":
    case "Lead_SA":
      return allNavItems;
    case "Admin":
      return allNavItems;
    default:
      // Jika role belum diketahui, tampilkan minimal
      return allNavItems.filter((item) =>
        ["Dashboard", "Proyek"].includes(item.label)
      );
  }
}

export function Sidebar() {
  const { isOpen, toggle } = useSidebarStore();
  const { user, clearUser } = useAuthStore();
  const pathname = usePathname();

  // Dapatkan item navigasi sesuai role
  const navItems = getNavItemsForRole(user?.role);

  /** Logout: reset store lalu revoke session + redirect ke /login */
  const handleLogout = () => {
    clearUser();
    void logout();
  };

  return (
    <aside
      className={`
        flex flex-col bg-white border-r border-neutral-200 
        transition-all duration-200 ease-in-out
        h-screen shrink-0
        ${isOpen ? "w-[240px]" : "w-[64px]"}
      `}
    >
      {/* Logo dan toggle */}
      <div className="flex items-center justify-between h-[64px] px-4 border-b border-neutral-100">
        {isOpen && (
          <Link
            href="/"
            className="text-lg font-semibold text-primary-600 truncate hover:text-primary-700"
          >
            Portal SA
          </Link>
        )}
        <button
          onClick={toggle}
          className="flex items-center justify-center w-[44px] h-[44px] rounded-lg 
                     hover:bg-neutral-100 transition-colors duration-100"
          aria-label={isOpen ? "Tutup sidebar" : "Buka sidebar"}
          title={isOpen ? "Tutup sidebar" : "Buka sidebar"}
        >
          <svg
            className={`w-5 h-5 text-neutral-600 transition-transform duration-200 ${
              isOpen ? "" : "rotate-180"
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
            />
          </svg>
        </button>
      </div>

      {/* Navigation links */}
      <nav className="flex-1 py-4 overflow-y-auto">
        <ul className="space-y-1 px-2">
          {navItems.map((item) => {
            const IconComponent = item.icon;
            // Cek apakah link aktif (exact match untuk "/" atau startsWith untuk lainnya)
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`
                    flex items-center gap-3 rounded-lg px-3 
                    min-h-[44px] min-w-[44px]
                    transition-colors duration-100
                    ${isOpen ? "" : "justify-center"}
                    ${
                      isActive
                        ? "bg-primary-50 text-primary-600 font-medium"
                        : "text-neutral-700 hover:bg-neutral-100 hover:text-primary-600"
                    }
                  `}
                  title={item.label}
                >
                  <IconComponent className="w-5 h-5 shrink-0" />
                  {isOpen && (
                    <span className="text-sm font-medium truncate">
                      {item.label}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}

          {/* Admin-only menu items */}
          {user?.role === "Admin" && (
            <>
              <li className="pt-3 mt-3 border-t border-neutral-100">
                {isOpen && (
                  <span className="px-3 text-xs font-semibold text-neutral-400 uppercase">
                    Admin
                  </span>
                )}
              </li>
              {adminNavItems.map((item) => {
                const IconComponent = item.icon;
                const isActive = pathname.startsWith(item.href);

                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`
                        flex items-center gap-3 rounded-lg px-3 
                        min-h-[44px] min-w-[44px]
                        transition-colors duration-100
                        ${isOpen ? "" : "justify-center"}
                        ${
                          isActive
                            ? "bg-primary-50 text-primary-600 font-medium"
                            : "text-neutral-700 hover:bg-neutral-100 hover:text-primary-600"
                        }
                      `}
                      title={item.label}
                    >
                      <IconComponent className="w-5 h-5 shrink-0" />
                      {isOpen && (
                        <span className="text-sm font-medium truncate">
                          {item.label}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </>
          )}
        </ul>
      </nav>

      {/* Footer — info user + logout */}
      <div className="border-t border-neutral-100 p-3 space-y-2">
        <UserMenu placement="up" align="left" showDetails={isOpen} />

        {/* Tombol Logout */}
        <button
          onClick={handleLogout}
          className={`flex items-center gap-3 rounded-lg px-3 w-full
            min-h-[44px] text-sm font-medium
            text-neutral-600 hover:bg-red-50 hover:text-red-600
            transition-colors duration-100
            ${isOpen ? "" : "justify-center"}`}
          title="Keluar"
          aria-label="Keluar"
        >
          <svg
            className="w-5 h-5 shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
            />
          </svg>
          {isOpen && <span>Keluar</span>}
        </button>
      </div>
    </aside>
  );
}
