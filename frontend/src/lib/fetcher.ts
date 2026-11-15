/**
 * SWR Fetcher Configuration untuk Portal SA
 *
 * Konfigurasi data fetching menggunakan SWR dengan:
 * - Base URL dari environment variable
 * - Auto-attach auth token ke request header
 * - Standard error handling sesuai API response format
 * - Revalidation strategy untuk freshness data
 */

// Base URL API backend
// Jika NEXT_PUBLIC_API_URL tidak di-set saat build, gunakan relative path
// agar Nginx reverse proxy handle routing ke backend
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "/api/v1";

let accessToken: string | null = null;
let refreshInFlight: Promise<{ token: string | null; detail?: string }> | null = null;
const refreshDetailsByResponse = new WeakMap<Response, string>();

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function refreshAccessToken(): Promise<{ token: string | null; detail?: string }> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          return { token: null, detail: body?.detail };
        }
        const result = await response.json();
        accessToken = result.access_token;
        return { token: accessToken };
      })
      .catch(() => ({ token: null }))
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

async function authenticatedFetch(url: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(url, { ...init, headers, credentials: "include" });
  if (response.status !== 401 || url.endsWith("/auth/refresh")) return response;

  const refresh = await refreshAccessToken();
  if (!refresh.token) {
    if (refresh.detail) refreshDetailsByResponse.set(response, refresh.detail);
    return response;
  }
  headers.set("Authorization", `Bearer ${refresh.token}`);
  return fetch(url, { ...init, headers, credentials: "include" });
}

/**
 * Error class khusus untuk API errors
 * Menyimpan status code dan response data untuk handling di UI
 */
export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/**
 * Fetcher default untuk SWR
 * Menghandle auth header dan standard error response
 *
 * Penggunaan dengan SWR:
 *   const { data, error } = useSWR("/projects", fetcher);
 */
export async function fetcher<T>(endpoint: string): Promise<T> {
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;

  const headers = new Headers({
    "Content-Type": "application/json",
  });

  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await authenticatedFetch(url, { headers });

  // Handle response sesuai standard format API:
  // { status: "success|error", data: {...}, message: "..." }
  if (!response.ok) {
    // Handle 401 — hapus token dan redirect ke login
    if (response.status === 401) {
      if (typeof window !== "undefined") {
        clearAccessToken();
        window.location.href =
          refreshDetailsByResponse.get(response) === "Refresh cookie tidak ditemukan."
            ? "/login"
            : "/login?error=session_expired";
      }
      throw new ApiError("Unauthorized", 401, { refreshDetail: refreshDetailsByResponse.get(response) });
    }

    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message || `Request gagal dengan status ${response.status}`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/**
 * POST/PUT/PATCH/DELETE request helper
 * Untuk mutasi data yang bukan GET request
 */
export async function apiRequest<T>(
  endpoint: string,
  options: {
    method?: "POST" | "PUT" | "PATCH" | "DELETE";
    body?: unknown;
  } = {}
): Promise<T> {
  const { method = "POST", body } = options;
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };

  const response = await authenticatedFetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      errorData?.message || `Request gagal dengan status ${response.status}`,
      response.status,
      errorData
    );
  }

  const json = await response.json();
  return json.data ?? json;
}

/** Opsi `apiCall`: satu pintu untuk klien API di `lib/api/*` (menggantikan `fetch` langsung). */
export interface ApiCallOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** `FormData` dikirim apa adanya (tanpa Content-Type, boundary dari browser); lainnya di-JSON-kan. */
  body?: unknown;
  /** Pesan bila backend tidak memberi pesan; status HTTP ditambahkan: `${pesanGagal} (status N)`. */
  pesanGagal: string;
  /** Pilih pesan dari body error backend; kembalian kosong memakai `pesanGagal`. Bawaan: `message`. */
  ambilPesan?: (errorData: Record<string, unknown> | null) => string | undefined | null;
  /** Status yang bukan error: `apiCall` mengembalikan `null` tanpa membaca body (mis. 404 = belum ada). */
  terimaStatus?: number[];
  /** Abaikan body respons sukses (mis. 204/ tanpa konten). */
  tanpaBody?: boolean;
}

/**
 * Request ke API dengan access token memory, refresh cookie HttpOnly, dan `ApiError` standar.
 *
 * Penanganan 401 mengikuti pola yang sudah ada: GET seperti `fetcher` (hapus token, ke /login),
 * mutasi seperti `apiRequest` (hanya `ApiError`, tanpa logout otomatis).
 * Mengembalikan body JSON mentah; pemanggil membuka envelope (`json.data ?? json`) sendiri.
 */
export async function apiCall(endpoint: string, opsi: ApiCallOptions): Promise<any> {
  const { method = "GET", body, pesanGagal, ambilPesan, terimaStatus, tanpaBody } = opsi;
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE_URL}${endpoint}`;
  const multipart = typeof FormData !== "undefined" && body instanceof FormData;
  const headers: Record<string, string> = {};
  // Multipart: jangan set Content-Type, browser menambahkan boundary.
  if (!multipart) headers["Content-Type"] = "application/json";
  const response = await authenticatedFetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : multipart ? (body as FormData) : JSON.stringify(body),
  });

  if (!response.ok) {
    if (terimaStatus?.includes(response.status)) return null;

    if (response.status === 401 && method === "GET") {
      if (typeof window !== "undefined") {
        clearAccessToken();
        window.location.href = "/login?error=session_expired";
      }
      throw new ApiError("Unauthorized", 401);
    }

    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      ambilPesan?.(errorData) || errorData?.message || `${pesanGagal} (status ${response.status})`,
      response.status,
      errorData
    );
  }

  if (tanpaBody) return undefined;
  return response.json();
}

/**
 * Konfigurasi default SWR
 * Digunakan di SWRConfig provider
 *
 * - Revalidation on focus: aktif (data fresh saat user kembali ke tab)
 * - Revalidation on reconnect: aktif (sync saat online kembali)
 * - Retry: 3 kali dengan exponential backoff
 * - Dedupe interval: 2 detik
 */
export const swrConfig = {
  fetcher,
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  errorRetryCount: 3,
  dedupingInterval: 2000,
  // Jangan retry jika unauthorized (401) — redirect ke login
  onErrorRetry: (
    error: ApiError,
    _key: string,
    _config: unknown,
    revalidate: (opts?: { retryCount: number }) => void,
    { retryCount }: { retryCount: number }
  ) => {
    if (error.status === 401) return;
    if (error.status === 403) return;
    if (retryCount >= 3) return;

    // Exponential backoff
    const timeout = Math.min(1000 * 2 ** retryCount, 30000);
    setTimeout(() => revalidate({ retryCount }), timeout);
  },
};
