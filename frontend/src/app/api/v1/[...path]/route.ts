import { NextRequest, NextResponse } from "next/server";

/**
 * API Route Proxy — catch-all untuk /api/v1/*
 *
 * Meneruskan semua request ke backend container via Docker network.
 * Ini lebih reliable daripada middleware atau rewrites di standalone mode.
 *
 * Endpoint: /api/v1/[...path]
 * Backend: http://backend:8000/api/v1/[...path]
 */

const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";
const FRONTEND_URL = process.env.FRONTEND_URL || "http://localhost:3000";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path, "GET");
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path, "POST");
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path, "PUT");
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path, "PATCH");
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path, "DELETE");
}

/**
 * Proxy request ke backend container
 */
async function proxyRequest(
  request: NextRequest,
  pathSegments: string[],
  method: string
) {
  const path = pathSegments.join("/");
  const searchParams = request.nextUrl.searchParams.toString();
  const queryString = searchParams ? `?${searchParams}` : "";
  const backendUrl = `${BACKEND_URL}/api/v1/${path}${queryString}`;

  // Log hanya method + path. Jangan cetak query string (kode OAuth sekali pakai, state), header
  // Location, atau body: semuanya bisa memuat token (#80).
  console.log(`[API Proxy] ${method} /api/v1/${path}`);

  try {
    // Build headers — forward semua kecuali host
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("connection");
    headers.delete("content-length"); // akan di-set ulang oleh fetch

    // Forward request body untuk POST/PUT/PATCH
    const fetchOptions: RequestInit = {
      method,
      headers,
      redirect: "manual",
    };

    if (method !== "GET" && method !== "HEAD") {
      fetchOptions.body = await request.text();
    }

    const response = await fetch(backendUrl, fetchOptions);

    console.log(`[API Proxy] ← ${response.status} ${response.statusText} (${method} /api/v1/${path})`);

    // Forward response headers
    const responseHeaders = new Headers();
    response.headers.forEach((value, key) => {
      // Skip hop-by-hop headers
      if (!["transfer-encoding", "connection", "keep-alive"].includes(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });

    // Read response body
    const body = await response.text();

    // Special handling: auth/callback → redirect ke frontend callback page
    // Google OAuth redirect ke /api/v1/auth/callback (API route), bukan
    // frontend page. Jadi kita perlu redirect ke /auth/callback dengan data.
    if (path === "auth/callback") {
      // Calendar Auth Flow: backend membalas 3xx redirect ke
      // {frontend_url}#gcal_code=... (atau #gcal_error=...).
      // Karena proxy pakai redirect:"manual", redirect itu TIDAK diikuti —
      // kita teruskan Location agar kode handoff singkat sampai ke browser.
      // sampai ke halaman calendar. Tanpa ini, flow jatuh ke cabang error
      // di bawah dan user salah diarahkan ke /login.
      if (response.status >= 300 && response.status < 400) {
        const location = response.headers.get("location");
        if (location) {
          const tujuan = new URL(location, FRONTEND_URL);
          const parameter = new URLSearchParams(tujuan.search);
          const fragment = new URLSearchParams(tujuan.hash.slice(1));
          const memuatToken = [...parameter.keys(), ...fragment.keys()].some((key) =>
            /token/i.test(key),
          );
          if (tujuan.origin !== new URL(FRONTEND_URL).origin || memuatToken) {
            console.error("[API Proxy] auth/callback redirect ditolak (tujuan tidak aman)");
            return NextResponse.redirect(new URL("/login?error=auth_failed", FRONTEND_URL));
          }
          console.log(`[API Proxy] ← auth/callback redirect (calendar flow)`);
          return NextResponse.redirect(tujuan);
        }
      }

      if (response.status === 200) {
        try {
          const data = JSON.parse(body);
          if (data.handoff_code) {
            const params = new URLSearchParams({ code: data.handoff_code });
            const redirectUrl = `${FRONTEND_URL}/auth/callback?${params.toString()}`;
            console.log(`[API Proxy] ← auth/callback sukses, redirect ke /auth/callback`);
            return NextResponse.redirect(redirectUrl);
          }
        } catch (e) {
          console.error(`[API Proxy] ERROR parsing auth/callback response:`, e);
        }
      } else {
        // Error dari backend (403 domain_not_allowed, dll) → redirect ke login
        let errorCode = "auth_failed";
        try {
          const errData = JSON.parse(body);
          if (response.status === 403) errorCode = "domain_not_allowed";
          else if (errData?.detail) errorCode = errData.detail;
        } catch (e) { /* ignore */ }
        console.log(`[API Proxy] ← auth/callback error ${response.status}, redirect ke /login`);
        return NextResponse.redirect(
          new URL(`/login?error=${errorCode}`, FRONTEND_URL)
        );
      }
    }

    return new NextResponse(body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(`[API Proxy] ERROR: ${method} /api/v1/${path}`, error);
    return NextResponse.json(
      {
        status: "error",
        message: `Backend tidak tersedia: ${error instanceof Error ? error.message : "Unknown error"}`,
      },
      { status: 502 }
    );
  }
}
