import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Konfigurasi Vitest frontend.
 *
 * Cakupan (v8): baris + cabang, dilaporkan per berkas. `include` diset eksplisit ke src/**
 * supaya berkas yang BELUM punya test tetap terhitung (default v8 hanya berkas yang diimpor test).
 *
 * Daftar pengecualian cakupan FINAL (dikunci di CONSTRAINTS.md bagian 3; jangan ditambah
 * tanpa prosedur bagian 4):
 * - `*.test.{ts,tsx}` — berkas test sendiri, bukan kode produk;
 * - `src/test/**` — utilitas/fixture/mock test, bukan kode produk;
 * - `*.d.ts` — deklarasi tipe murni, tanpa kode runtime.
 * Berkas lain (termasuk layout/halaman besar) sengaja TIDAK dikecualikan.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: false, // impor eksplisit describe/it/expect/vi
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    clearMocks: true,
    restoreMocks: true,
    // URL absolut: undici (fetch Node) tidak bisa me-resolve "/api/v1" relatif, dan
    // modul membaca env ini saat dimuat (konstanta modul), jadi harus diset di sini.
    env: { NEXT_PUBLIC_API_URL: "http://localhost/api/v1" },
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/**/*.d.ts"],
      reporter: ["text", "html", "lcov", "json-summary"],
      // Gerbang cakupan (CONSTRAINTS.md bagian 1, tiket #71): GLOBAL, selaras backend.
      // Di bawah ambang -> `vitest run --coverage` keluar dengan kode != 0. Jangan diturunkan.
      // Berkas individual di bawah ambang hanya diperingatkan (scripts/cakupan-ringkasan.mjs).
      thresholds: { lines: 90, branches: 80 },
    },
  },
});
