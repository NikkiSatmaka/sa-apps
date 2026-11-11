/**
 * Handler MSW untuk halaman autentikasi (tiket F3): login, demo, callback.
 *
 * `/auth/config`, `/auth/demo-login`, `/auth/me` dan `/auth/logout` sudah ada di `auth.ts` (default
 * `demo_mode: true`, `oauth_configured` tidak ada). Handler di berkas ini hanya MENAMBAH:
 * - `/auth/callback?code=...` (jalur fallback OAuth lama yang dipanggil halaman callback);
 * - `authConfig(...)` — fabrik untuk menimpa `/auth/config` per test lewat `server.use(authConfig({...}))`.
 *
 * Kode khusus untuk `/auth/callback`: `forbidden` → 403, `broken` → 500 (body bukan JSON),
 * kode lain apa pun → sukses dengan peran SA.
 */
import { http, HttpResponse } from "msw";
import { loginResponse } from "../../fixtures/users";
import { api } from "../base";

export function authConfig(config: { oauth_configured?: boolean; demo_mode?: boolean }) {
  return http.get(api("/auth/config"), () => HttpResponse.json(config));
}

export const authPagesHandlers = [
  http.get(api("/auth/callback"), ({ request }) => {
    const code = new URL(request.url).searchParams.get("code");
    if (code === "forbidden") {
      return HttpResponse.json({ status: "error", data: null, message: "Domain tidak diizinkan" }, { status: 403 });
    }
    if (code === "broken") return HttpResponse.text("kacau", { status: 500 });
    return HttpResponse.json(loginResponse("SA"));
  }),
];
