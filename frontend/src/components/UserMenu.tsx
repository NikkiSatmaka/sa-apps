"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { logout } from "@/lib/auth";

/**
 * UserMenu — dropdown akun pengguna (dipakai di Header dan footer Sidebar)
 *
 * Isi menu: info singkat user, link ke /profile, dan tombol Keluar.
 * Menutup saat klik di luar, tekan Escape, atau pilih item.
 */

interface UserMenuProps {
  /** Arah dropdown terbuka: "down" (header) atau "up" (footer sidebar) */
  placement?: "down" | "up";
  /** Tampilkan nama + role di samping avatar (sidebar terbuka) */
  showDetails?: boolean;
  /** Rata kiri/kanan dropdown terhadap trigger */
  align?: "left" | "right";
  className?: string;
}

export function UserMenu({
  placement = "down",
  showDetails = false,
  align = "right",
  className = "",
}: UserMenuProps) {
  const { user, clearUser } = useAuthStore();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const initial = user?.full_name?.charAt(0)?.toUpperCase() || "U";

  const handleLogout = () => {
    setOpen(false);
    clearUser();
    void logout();
  };

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-3 rounded-lg min-h-[44px] min-w-[44px] px-1.5
                   hover:bg-neutral-100 transition-colors duration-100 w-full"
        aria-label="Menu pengguna"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="w-8 h-8 rounded-full bg-primary-500 flex items-center justify-center shrink-0 overflow-hidden">
          <span className="text-sm font-medium text-white">{initial}</span>
        </span>
        {showDetails && (
          <span className="truncate text-left">
            <span className="block text-sm font-medium text-neutral-700 truncate">
              {user?.full_name || "User"}
            </span>
            <span className="block text-xs text-neutral-400 truncate">
              {user?.role || "—"}
            </span>
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute z-50 w-60 rounded-lg border border-neutral-200 bg-white shadow-lg py-1
            ${placement === "up" ? "bottom-full mb-2" : "top-full mt-2"}
            ${align === "left" ? "left-0" : "right-0"}`}
        >
          <div className="px-4 py-3 border-b border-neutral-100">
            <p className="text-sm font-medium text-neutral-900 truncate">
              {user?.full_name || "User"}
            </p>
            <p className="text-xs text-neutral-500 truncate">{user?.email}</p>
            <p className="text-xs text-neutral-400 mt-0.5">{user?.role}</p>
          </div>

          <Link
            href="/profile"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center min-h-[44px] px-4 text-sm text-neutral-700 hover:bg-neutral-100"
          >
            Profil Saya
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="flex items-center w-full min-h-[44px] px-4 text-sm text-neutral-700 hover:bg-red-50 hover:text-red-600"
          >
            Keluar
          </button>
        </div>
      )}
    </div>
  );
}
