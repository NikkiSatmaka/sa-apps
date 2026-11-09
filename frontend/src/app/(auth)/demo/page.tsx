"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";

/**
 * Halaman Demo Login Portal SA
 *
 * Menampilkan tombol demo login per role (Sales, SA, Lead SA, Admin).
 * Klik tombol demo → POST ke /auth/demo-login → simpan token → redirect dashboard.
 *
 * Halaman ini terpisah dari /login (yang hanya menampilkan Google OAuth).
 */

const ERROR_MESSAGES: Record<string, string> = {
  domain_not_allowed:
    "Domain email Anda tidak diizinkan untuk mengakses sistem ini.",
  auth_cancelled: "Login dibatalkan.",
  auth_failed: "Login gagal. Silakan coba lagi.",
};

// Konfigurasi tombol demo login per role
const DEMO_ROLES = [
  {
    role: "Sales",
    label: "Login sebagai Sales",
    color: "bg-blue-600 hover:bg-blue-700 focus:ring-blue-500",
  },
  {
    role: "SA",
    label: "Login sebagai SA",
    color: "bg-green-600 hover:bg-green-700 focus:ring-green-500",
  },
  {
    role: "Lead_SA",
    label: "Login sebagai Lead SA",
    color: "bg-purple-600 hover:bg-purple-700 focus:ring-purple-500",
  },
  {
    role: "Admin",
    label: "Login sebagai Admin",
    color: "bg-red-600 hover:bg-red-700 focus:ring-red-500",
  },
] as const;

function DemoContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setUser } = useAuthStore();
  const error = searchParams.get("error");
  const [loadingRole, setLoadingRole] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  // null = belum diketahui; false = demo mode nonaktif (redirect ke /login)
  const [demoEnabled, setDemoEnabled] = useState<boolean | null>(null);

  // Guard UI: halaman demo hanya boleh tampil jika backend mengaktifkan demo
  // mode. Backend tetap memblokir /auth/demo-login (403) sebagai penjaga utama.
  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api/v1";
    fetch(`${apiUrl}/auth/config`)
      .then((res) => res.json())
      .then((data) => setDemoEnabled(Boolean(data.demo_mode)))
      .catch(() => setDemoEnabled(false));
  }, []);

  useEffect(() => {
    if (demoEnabled === false) router.replace("/login");
  }, [demoEnabled, router]);
  const errorMessage =
    error && (ERROR_MESSAGES[error] || "Terjadi kesalahan. Silakan coba lagi.");

  /**
   * Handler demo login — POST ke backend lalu simpan token dan user info
   */
  const handleDemoLogin = async (role: string) => {
    setLoadingRole(role);
    setLoginError(null);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

      const response = await fetch(`${apiUrl}/auth/demo-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(
          errorData?.message || `Login gagal (${response.status})`
        );
      }

      const data = await response.json();

      // Handle berbagai struktur response dari backend:
      // Struktur 1: { access_token, refresh_token, user }
      // Struktur 2: { tokens: { access_token, refresh_token }, user }
      // Struktur 3: { data: { tokens: {...}, user: {...} } }
      const tokens = data.tokens || data.data?.tokens || data;
      const userData = data.user || data.data?.user;

      // Simpan token ke localStorage
      const accessToken = tokens.access_token;
      const refreshToken = tokens.refresh_token;

      if (accessToken) {
        localStorage.setItem("access_token", accessToken);
      }
      if (refreshToken) {
        localStorage.setItem("refresh_token", refreshToken);
      }

      // Simpan user info ke Zustand auth store
      if (userData) {
        setUser({
          id: userData.id,
          email: userData.email,
          full_name: userData.name || userData.full_name,
          role: userData.role,
          avatar_url: userData.avatar_url,
        });
      }

      // Redirect ke dashboard
      router.push("/");
    } catch (err) {
      setLoginError(
        err instanceof Error ? err.message : "Login gagal. Silakan coba lagi."
      );
    } finally {
      setLoadingRole(null);
    }
  };

  if (demoEnabled !== true) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo / App Name */}
        <div className="text-center">
          <h1 className="text-3xl font-bold text-primary-600">Portal SA</h1>
          <p className="mt-2 text-sm text-neutral-500">
            Manajemen Proyek Pre-Sales
          </p>
        </div>

        {/* Banner Demo Mode */}
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 text-center"
          role="status"
        >
          Demo Mode — Login tanpa Google OAuth
        </div>

        {/* Error messages */}
        {(errorMessage || loginError) && (
          <div
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {loginError || errorMessage}
          </div>
        )}

        {/* Demo Login Buttons */}
        <div className="rounded-xl border border-neutral-200 bg-white p-6 shadow-sm space-y-3">
          <p className="mb-4 text-center text-sm text-neutral-600">
            Pilih role untuk demo login
          </p>

          {DEMO_ROLES.map(({ role, label, color }) => (
            <button
              key={role}
              onClick={() => handleDemoLogin(role)}
              disabled={loadingRole !== null}
              className={`
                flex w-full items-center justify-center rounded-lg px-4 py-3 
                min-h-[44px] text-sm font-medium text-white shadow-sm
                transition-colors duration-100
                focus:outline-none focus:ring-2 focus:ring-offset-2
                disabled:opacity-50 disabled:cursor-not-allowed
                ${color}
              `}
            >
              {loadingRole === role ? (
                <span className="flex items-center gap-2">
                  <svg
                    className="w-4 h-4 animate-spin"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  Memproses...
                </span>
              ) : (
                label
              )}
            </button>
          ))}
        </div>

        {/* Link kembali ke login Google */}
        <p className="text-center text-sm">
          <Link
            href="/login"
            className="text-primary-600 hover:text-primary-700 font-medium"
          >
            Login dengan Google Account
          </Link>
        </p>

        {/* Footer */}
        <p className="text-center text-xs text-neutral-400">
          Mode demo aktif — semua data bersifat sementara.
        </p>
      </div>
    </div>
  );
}

export default function DemoPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-neutral-50">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      }
    >
      <DemoContent />
    </Suspense>
  );
}
