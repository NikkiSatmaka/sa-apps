# Frontend — Portal SA

Next.js 16 (App Router) + React 19 + TypeScript. Gambaran produk dan setup lengkap ada di [README root](../README.md) dan [CONTRIBUTING.md](../CONTRIBUTING.md).

## Perintah

| Perintah | Fungsi |
| --- | --- |
| `pnpm dev` / `pnpm build` | Dev server / build produksi |
| `pnpm exec tsc --noEmit` | Type-check (mencakup berkas test) |
| `pnpm test` | Jalankan semua test sekali (Vitest) |
| `pnpm test:watch` | Mode watch |
| `pnpm test:coverage` | Test + laporan cakupan v8 per berkas (baris + cabang; HTML di `coverage/`) |

`pnpm lint` (`next lint`) tidak berfungsi di Next 16 dan belum diganti.

## Testing

Stack: Vitest (jsdom), React Testing Library, user-event, MSW, cakupan v8. Semua versi dipin eksak.
Konfigurasi di `vitest.config.mts` (alias `@/`, `NEXT_PUBLIC_API_URL=http://localhost/api/v1` absolut,
daftar pengecualian cakupan di komentar config). Test diletakkan berdampingan dengan kodenya: `X.test.ts(x)`.

Utilitas bersama ada di `src/test/` dan diimpor dari `@/test`:

```tsx
import { renderWithProviders, seedAuth, setParams, setPathname, router, server, http, HttpResponse, api, stubLocation, setOnline } from "@/test";
import { makeProject } from "@/test/fixtures/projects";
```

- **`renderWithProviders(ui, { role? })`** — render dengan `SWRConfig` ber-cache baru (tanpa retry/dedupe) dan, bila `role` diberikan, seeding auth. Mengembalikan `user` (user-event) selain hasil `render`.
- **`seedAuth("Sales" | "SA" | "Lead_SA" | "Admin")`** — mengisi store auth + token palsu di `localStorage`.
- **Mock `next/navigation`** — terpasang otomatis di setup. Atur lewat `setParams({ id })`, `setPathname("/x")`, `setSearchParams("a=1")`; periksa navigasi lewat `router.push` / `router.replace` (`vi.fn`).
- **MSW** — handler default di `src/test/msw/handlers/` (auth/demo-login, proyek, dokumen, skema kuesioner, notifikasi). Timpa per test dengan `server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope([...]))))`. Request tanpa handler **gagal** (`onUnhandledFrame: "error"`). Tiket baru menambah handler di berkas grup sendiri lalu mendaftarkannya di `handlers/index.ts`.
- **Fixture** — `src/test/fixtures/*` berbentuk persis respons backend (envelope `{status, data, message}` lewat `successEnvelope`/`errorEnvelope`; `loginResponse(role)` tanpa envelope, seperti backend). Pakai `makeX(overrides)`.
- **Stub jsdom** — `stubLocation()` (cek `window.location.href`/`reload`), `setOnline(false)`; `window.confirm` default menyetujui.
- **Reset otomatis per test** (di `src/test/setup.ts`): localStorage, store auth/toast/sidebar, mock router, timer palsu, stub global, handler MSW.

Catatan MSW 3: opsi `onUnhandledRequest` sudah diganti `onUnhandledFrame`. Aplikasi tidak memasang `SWRConfig`; isolasi cache SWR hanya terjadi lewat `renderWithProviders`.
