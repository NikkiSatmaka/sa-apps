"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { Suspense } from "react";

/**
 * OAuth Callback Handler
 *
 * Halaman ini menerima callback dari backend setelah OAuth flow.
 * Flow:
 * 1. Backend redirect ke halaman ini dengan query params (code)
 * 2. Halaman ini memanggil backend /auth/callback dengan code tersebut
 * 3. Simpan tokens ke localStorage
 * 4. Update auth store dengan data user
 * 5. Redirect ke dashboard (/) jika berhasil, atau /login?error=xxx jika gagal
 */

function CallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser, setLoading } = useAuthStore();
  const hasProcessed = useRef(false);

  useEffect(() => {
    // Hindari double-processing di React Strict Mode
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const processCallback = async () => {
      setLoading(true);

      // Token OAuth datang di URL hash (fragment), bukan query string, agar
      // tidak bocor ke server/log. Hash hanya tersedia di client.
      const hashParams =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.hash.slice(1))
          : new URLSearchParams();

      const accessToken = hashParams.get("access_token");
      const refreshToken = hashParams.get("refresh_token");
      const userParam = hashParams.get("user");
      // code & error tetap dibaca dari query string (jalur fallback OAuth lama).
      const code = searchParams.get("code");
      const error = searchParams.get("error");

      // Handle jika Google mengembalikan error (user batal consent)
      if (error) {
        router.replace("/login?error=auth_cancelled");
        return;
      }

      // Handle redirect dari API proxy (tokens sudah ada di URL)
      if (accessToken && userParam) {
        try {
          const userData = JSON.parse(decodeURIComponent(userParam));

          // Simpan tokens ke localStorage
          localStorage.setItem("access_token", accessToken);
          if (refreshToken) {
            localStorage.setItem("refresh_token", refreshToken);
          }

          // Bersihkan hash agar token tidak tertinggal di URL (pola CalendarSync).
          if (typeof window !== "undefined") {
            window.history.replaceState(
              null,
              "",
              window.location.pathname + window.location.search
            );
          }

          // Update auth store dengan data user
          setUser({
            id: userData.id,
            email: userData.email,
            full_name: userData.name || userData.full_name,
            role: userData.role,
            is_admin: userData.is_admin === true,
            avatar_url: userData.avatar_url,
          });

          // Redirect ke dashboard
          router.replace("/");
        } catch (err) {
          console.error("Error processing token from URL:", err);
          router.replace("/login?error=auth_failed");
        }
        return;
      }

      // Handle jika tidak ada code maupun token
      if (!code) {
        router.replace("/login?error=auth_failed");
        return;
      }

      try {
        const apiUrl =
          process.env.NEXT_PUBLIC_API_URL || "/api/v1";

        const response = await fetch(
          `${apiUrl}/auth/callback?code=${encodeURIComponent(code)}`,
          {
            method: "GET",
            headers: { "Content-Type": "application/json" },
          }
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => null);

          // Handle domain tidak diizinkan (403)
          if (response.status === 403) {
            router.replace("/login?error=domain_not_allowed");
            return;
          }

          // Handle error lainnya
          console.error("Auth callback error:", errorData);
          router.replace("/login?error=auth_failed");
          return;
        }

        const data = await response.json();

        // Simpan tokens ke localStorage
        localStorage.setItem("access_token", data.tokens.access_token);
        localStorage.setItem("refresh_token", data.tokens.refresh_token);

        // Update auth store dengan data user
        setUser({
          id: data.user.id,
          email: data.user.email,
          full_name: data.user.name,
          role: data.user.role,
          is_admin: data.user.is_admin === true,
          avatar_url: data.user.avatar_url,
        });

        // Redirect ke dashboard
        router.replace("/");
      } catch (err) {
        console.error("Callback processing error:", err);
        router.replace("/login?error=auth_failed");
      }
    };

    processCallback();
  }, [searchParams, router, setUser, setLoading]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50">
      <div className="text-center space-y-4">
        <div className="h-8 w-8 mx-auto animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        <p className="text-sm text-neutral-500">Memproses login...</p>
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-neutral-50">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
