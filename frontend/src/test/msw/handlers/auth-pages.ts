/**
 * Handler MSW untuk halaman autentikasi (tiket F3): login, demo, callback.
 *
 * `/auth/config`, `/auth/demo-login`, `/auth/me` dan `/auth/logout` sudah ada di `auth.ts` (default
 * `demo_mode: true`, `oauth_configured` tidak ada). Handler di berkas ini hanya MENAMBAH:
 * - `/auth/callback/exchange` (penukaran handoff code sekali pakai);
 * - `authConfig(...)` — fabrik untuk menimpa `/auth/config` per test lewat `server.use(authConfig({...}))`.
 *
 * Kode khusus untuk exchange: `forbidden` → 403, `broken` → 500 (body bukan JSON),
 * kode lain apa pun → sukses dengan peran SA.
 */
import { http, HttpResponse } from "msw";
import { loginResponse } from "../../fixtures/users";
import { api } from "../base";

export function authConfig(config: { oauth_configured?: boolean; demo_mode?: boolean }) {
  return http.get(api("/auth/config"), () => HttpResponse.json(config));
}

export const authPagesHandlers = [
  http.post(api("/auth/callback/exchange"), async ({ request }) => {
    const { code } = (await request.json()) as { code: string };
    if (code === "forbidden") {
      return HttpResponse.json({ status: "error", data: null, message: "Domain tidak diizinkan" }, { status: 403 });
    }
    if (code === "broken") return HttpResponse.text("kacau", { status: 500 });
    const login = loginResponse("SA");
    return HttpResponse.json({ user: login.user, access_token: login.tokens.access_token, expires_in: 900 });
  }),
];
