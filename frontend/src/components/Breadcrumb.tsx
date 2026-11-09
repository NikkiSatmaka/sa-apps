"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Breadcrumb dinamis berdasarkan pathname.
 *
 * - "Portal SA" selalu menaut ke "/" (dashboard).
 * - Setiap segmen perantara menjadi link; segmen terakhir = halaman aktif (bukan link).
 * - Segmen yang tidak punya halaman sendiri (mis. /admin, /dashboard) tidak dijadikan link.
 * - Segmen dinamis (UUID / id) diberi label "Detail".
 */

const SEGMENT_LABELS: Record<string, string> = {
  projects: "Proyek",
  new: "Proyek Baru",
  edit: "Edit",
  documents: "Dokumen",
  "activity-logs": "Activity Log",
  calendar: "Kalender",
  notifications: "Notifikasi",
  admin: "Admin",
  settings: "Settings",
  profile: "Profil",
  dashboard: "Dashboard",
  sales: "Sales",
  sa: "SA",
  "lead-sa": "Lead SA",
};

/** Path yang tidak punya page.tsx — tampilkan sebagai teks biasa */
const NON_LINKABLE = new Set(["/admin", "/dashboard"]);

interface Crumb {
  label: string;
  href: string;
}

function buildCrumbs(pathname: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  return segments.map((segment, i) => ({
    label: SEGMENT_LABELS[segment] ?? "Detail",
    href: "/" + segments.slice(0, i + 1).join("/"),
  }));
}

export function Breadcrumb() {
  const pathname = usePathname();
  const crumbs = buildCrumbs(pathname);
  // min-h-0/min-w-0: batalkan aturan global touch target 44px (globals.css) agar baseline sejajar
  const linkClass = "min-h-0 min-w-0 hover:text-primary-600 hover:underline";

  return (
    <nav aria-label="Breadcrumb" className="hidden md:flex items-center text-sm text-neutral-500">
      {crumbs.length === 0 ? (
        <>
          <Link href="/" className={linkClass}>
            Portal SA
          </Link>
          <span className="mx-2" aria-hidden="true">/</span>
          <span className="text-neutral-900 font-medium" aria-current="page">
            Dashboard
          </span>
        </>
      ) : (
        <>
          <Link href="/" className={linkClass}>
            Portal SA
          </Link>
          {crumbs.map((crumb, i) => {
            const isLast = i === crumbs.length - 1;
            return (
              <span key={crumb.href} className="flex items-center">
                <span className="mx-2" aria-hidden="true">/</span>
                {isLast ? (
                  <span className="text-neutral-900 font-medium" aria-current="page">
                    {crumb.label}
                  </span>
                ) : NON_LINKABLE.has(crumb.href) ? (
                  <span>{crumb.label}</span>
                ) : (
                  <Link href={crumb.href} className={linkClass}>
                    {crumb.label}
                  </Link>
                )}
              </span>
            );
          })}
        </>
      )}
    </nav>
  );
}
