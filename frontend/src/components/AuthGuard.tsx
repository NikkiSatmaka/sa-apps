"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { ApiError, clearAccessToken, fetcher, getAccessToken } from "@/lib/fetcher";

/**
 * AuthGuard Component
 *
 * Membungkus konten yang memerlukan autentikasi.
 * - Pada mount: pulihkan access token memory lewat refresh cookie HttpOnly
 * - Validasi token yang baru dengan GET /auth/me
 * - Jika valid: render children, update auth store
 * - Jika invalid (401): hapus token, redirect ke /login
 * - Tampilkan loading skeleton selama proses pengecekan
 */

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const { isAuthenticated, isLoading, setUser, clearUser, setLoading } =
    useAuthStore();

  useEffect(() => {
    const checkAuth = async () => {
      // Sudah authenticated (store sudah punya user data) — skip fetch
      if (isAuthenticated && getAccessToken()) {
        setLoading(false);
        return;
      }

      // fetcher mengelola refresh cookie, dedupe request serentak, dan satu retry 401.
      try {
        const userData = await fetcher<{
          id: string;
          email: string;
          name: string;
          role: "SA" | "Lead_SA" | "Sales" | "Product";
          is_admin?: boolean;
          avatar_url?: string;
        }>("/auth/me");

        // Update store dengan data user
        setUser({
          id: userData.id,
          email: userData.email,
          full_name: userData.name,
          role: userData.role,
          is_admin: userData.is_admin === true,
          avatar_url: userData.avatar_url,
        });
      } catch (error) {
        // Network error atau masalah lain — clear dan redirect
        clearAccessToken();
        clearUser();
        router.replace(
          error instanceof ApiError && error.status === 401 &&
          (error.data as { refreshDetail?: string } | undefined)?.refreshDetail !== "Refresh cookie tidak ditemukan."
            ? "/login?error=session_expired"
            : "/login",
        );
      }
    };

    checkAuth();
  }, [isAuthenticated, setUser, clearUser, setLoading, router]);

  // Tampilkan loading skeleton selama pengecekan auth
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-neutral-50">
        <div className="text-center space-y-4">
          <div className="h-8 w-8 mx-auto animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          <p className="text-sm text-neutral-500">Memuat...</p>
        </div>
      </div>
    );
  }

  // Jika belum authenticated dan tidak loading, jangan render children
  // (redirect sedang berlangsung)
  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
