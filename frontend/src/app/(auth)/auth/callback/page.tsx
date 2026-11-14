"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { Suspense } from "react";
import { setAccessToken } from "@/lib/fetcher";

/**
 * OAuth Callback Handler
 *
 * Halaman ini menerima callback dari backend setelah OAuth flow.
 * Flow:
 * 1. Backend redirect ke halaman ini dengan handoff code sekali pakai
 * 2. Halaman ini menukar code lewat POST; refresh token tetap di HttpOnly cookie
 * 3. Access token disimpan hanya di memory
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

      const code = searchParams.get("code");
      const error = searchParams.get("error");

      // Hapus fragment auth lama dari address bar; token fragment tidak lagi dipercaya.
      if (typeof window !== "undefined" && window.location.hash) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
      }

      // Handle jika Google mengembalikan error (user batal consent)
      if (error) {
        router.replace("/login?error=auth_cancelled");
        return;
      }

      if (!code) {
        router.replace("/login?error=auth_failed");
        return;
      }

      try {
        const apiUrl =
          process.env.NEXT_PUBLIC_API_URL || "/api/v1";

        const response = await fetch(
          `${apiUrl}/auth/callback/exchange`,
          {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code }),
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

        setAccessToken(data.access_token);

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
