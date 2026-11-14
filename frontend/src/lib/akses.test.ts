import { describe, expect, it } from "vitest";
import { izinkan, TINGKAT_AKSES, type HubunganProyek, type TingkatAkses } from "./akses";

const PROYEK = {
  salesPicId: "u-sales-pic",
  productPicId: "u-product-pic",
  saIds: ["u-sa-utama", "u-sa-tambahan"],
  kolaborator: [
    { user_id: "u-contrib", role: "contributor" },
    { user_id: "u-viewer", role: "viewer" },
  ],
} satisfies Omit<HubunganProyek, "actor">;

type Pengguna = { id: string; role: string; is_admin?: boolean };

const orang: Record<string, Pengguna> = {
  lead: { id: "u-lead", role: "Lead_SA" },
  admin: { id: "u-admin", role: "SA", is_admin: true },
  saUtama: { id: "u-sa-utama", role: "SA" },
  saTambahan: { id: "u-sa-tambahan", role: "SA" },
  saLain: { id: "u-sa-lain", role: "SA" },
  salesPic: { id: "u-sales-pic", role: "Sales" },
  productPic: { id: "u-product-pic", role: "Product" },
  salesLain: { id: "u-sales-lain", role: "Sales" },
  contributor: { id: "u-contrib", role: "Sales" },
  viewer: { id: "u-viewer", role: "SA" },
  luar: { id: "u-luar", role: "Product" },
};

/** Siapa yang berhak per tingkat; cermin `_ATURAN` di backend/app/core/dependencies.py. */
const BERHAK: Record<TingkatAkses, string[]> = {
  tulis: ["lead", "admin", "saUtama", "saTambahan", "contributor"],
  ubah_proyek: ["lead", "admin", "saUtama", "saTambahan", "salesPic", "productPic", "contributor"],
  kelola: ["lead", "admin", "saUtama", "saTambahan"],
  isi_dq: ["lead", "admin", "salesPic", "productPic"],
  tambah_kolaborator: ["lead", "admin", "saUtama", "saTambahan", "salesPic", "productPic"],
  hapus_kolaborator: ["lead", "admin", "saUtama", "saTambahan", "salesPic", "productPic"],
  handover: ["lead", "admin", "saUtama", "saTambahan"],
  kelola_requirement: ["lead", "admin", "saUtama", "saTambahan"],
  edit_kuesioner: ["lead", "admin", "salesPic", "productPic"],
  kelola_tim_sa: ["lead", "admin"],
  komentar: ["lead", "admin", "saUtama", "saTambahan", "salesPic", "productPic", "contributor"],
  buat_subtask: ["lead", "admin", "saUtama", "saTambahan"],
};

describe("izinkan — tabel hak per tingkat (cermin TingkatAkses backend)", () => {
  for (const tingkat of TINGKAT_AKSES) {
    for (const [nama, actor] of Object.entries(orang)) {
      const harusBoleh = BERHAK[tingkat].includes(nama);
      it(`${tingkat}: ${nama} ${harusBoleh ? "boleh" : "ditolak"}`, () => {
        expect(izinkan(tingkat, { ...PROYEK, actor })).toBe(harusBoleh);
      });
    }
  }

  it("daftar BERHAK mencakup semua tingkat yang diekspor", () => {
    expect([...TINGKAT_AKSES].sort()).toEqual(Object.keys(BERHAK).sort());
  });
});

describe("izinkan — kasus tepi", () => {
  it("tanpa actor: ditolak untuk semua tingkat", () => {
    for (const t of TINGKAT_AKSES) expect(izinkan(t, { ...PROYEK, actor: null })).toBe(false);
  });

  it("Sales PIC harus cocok id DAN peran bila aturan mencocokkan peran (edit_kuesioner)", () => {
    // id PIC tetapi peran SA: ditolak untuk edit_kuesioner, tetap boleh untuk ubah_proyek (tanpa cocok peran).
    const h = { ...PROYEK, actor: { id: "u-sales-pic", role: "SA" } };
    expect(izinkan("edit_kuesioner", h)).toBe(false);
    expect(izinkan("ubah_proyek", h)).toBe(true);
  });

  it("SA ditugaskan harus berperan SA bila aturan mencocokkan peran (buat_subtask)", () => {
    const h = { ...PROYEK, actor: { id: "u-sa-utama", role: "Sales" } };
    expect(izinkan("buat_subtask", h)).toBe(false);
    expect(izinkan("kelola", h)).toBe(true);
  });

  it("anggota SA tanpa id (null/undefined) di saIds diabaikan", () => {
    const h = { ...PROYEK, saIds: [null, undefined], actor: orang.saLain };
    expect(izinkan("kelola", h)).toBe(false);
  });

  it("peran collaborator tanpa nilai dianggap viewer (ditolak menulis)", () => {
    const h = { ...PROYEK, kolaborator: [{ user_id: "u-luar", role: null }], actor: orang.luar };
    expect(izinkan("tulis", h)).toBe(false);
  });

  it("saIds null (data tim SA belum dapat dimuat): SA berperan SA dibiarkan (opsi konservatif)", () => {
    const h = { ...PROYEK, saIds: null, actor: orang.saLain };
    expect(izinkan("kelola", h)).toBe(true);
    expect(izinkan("buat_subtask", h)).toBe(true);
    // Peran lain tidak ikut dibiarkan.
    expect(izinkan("kelola", { ...h, actor: orang.salesLain })).toBe(false);
    // Tingkat yang tidak memakai SA ditugaskan tidak terpengaruh.
    expect(izinkan("isi_dq", h)).toBe(false);
  });
});
