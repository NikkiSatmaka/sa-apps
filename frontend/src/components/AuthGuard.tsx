"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";

/**
 * AuthGuard Component
 *
 * Membungkus konten yang memerlukan autentikasi.
 * - Pada mount: cek apakah ada token di localStorage
 * - Jika ada token: validasi dengan GET /auth/me
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
      const token = localStorage.getItem("access_token");

      // Tidak ada token — langsung redirect ke login
      if (!token) {
        clearUser();
        router.replace("/login");
        return;
      }

      // Sudah authenticated (store sudah punya user data) — skip fetch
      if (isAuthenticated) {
        setLoading(false);
        return;
      }

      // Validasi token dengan backend
      try {
        const apiUrl =
          process.env.NEXT_PUBLIC_API_URL || "/api/v1";

        const response = await fetch(`${apiUrl}/auth/me`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });

        if (!response.ok) {
          // Token tidak valid — hapus dan redirect
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          clearUser();
          router.replace("/login");
          return;
        }

        const userData = await response.json();

        // Update store dengan data user
        setUser({
          id: userData.id,
          email: userData.email,
          full_name: userData.name,
          role: userData.role,
          is_admin: userData.is_admin === true,
          avatar_url: userData.avatar_url,
        });
      } catch {
        // Network error atau masalah lain — clear dan redirect
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        clearUser();
        router.replace("/login");
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
