/**
 * Regresi #81: halaman pengaturan admin (kredensial di localStorage) sudah dihapus.
 * Rute dan stub klien-nya tidak boleh ada lagi.
 */
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const src = resolve(__dirname, "../../..");

describe("penghapusan pengaturan admin (#81)", () => {
  it("rute /admin/settings tidak ada", () => {
    expect(existsSync(resolve(__dirname, "settings"))).toBe(false);
  });

  it("stub klien admin-settings tidak ada", () => {
    expect(existsSync(resolve(src, "lib/api/admin-settings.ts"))).toBe(false);
  });
});
