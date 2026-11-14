import { describe, expect, it } from "vitest";
import {
  aksiStatusTersedia,
  bisaHandover,
  QUALIFICATION_STATE,
  qualificationBadgeClass,
  STATUS_PROYEK,
  statusBadgeClass,
  type KonteksAksi,
} from "./status";

const SA_ID = "sa-1";
const SA_TAMBAHAN_ID = "sa-2";
const SALES_ID = "sales-1";
const PRODUCT_ID = "product-1";

const aktor = (role: string, is_admin = false, id = "x") => ({ id, role, is_admin });
const PERAN = {
  lead: aktor("Lead_SA", false, "lead-1"),
  admin: aktor("SA", true, "admin-1"),
  saUtama: aktor("SA", false, SA_ID),
  saTambahan: aktor("SA", false, SA_TAMBAHAN_ID),
  saLain: aktor("SA", false, "sa-lain"),
  salesPic: aktor("Sales", false, SALES_ID),
  productPic: aktor("Product", false, PRODUCT_ID),
  salesLain: aktor("Sales", false, "sales-lain"),
};

function kunci(status: string, actor: KonteksAksi["actor"], extra: Partial<KonteksAksi> = {}) {
  return aksiStatusTersedia({
    actor,
    status,
    salesPicId: SALES_ID,
    productPicId: PRODUCT_ID,
    saIds: [SA_ID, SA_TAMBAHAN_ID],
    ...extra,
  }).map((a) => a.kunci);
}

describe("daftar status baru (ADR 0013)", () => {
  it("memuat sepuluh status siklus kerja dan empat qualification_state, tanpa nama lama", () => {
    expect([...STATUS_PROYEK]).toEqual([
      "Intake", "Awaiting Assignment", "Assigned", "In Progress", "Submitted",
      "Won", "Handed Over", "Closed", "Lost", "On Hold",
    ]);
    expect([...QUALIFICATION_STATE]).toEqual(["Scoring", "Need Clarification", "Manual Review", "Qualified"]);
  });

  it("setiap status dan qualification_state punya kelas badge, dan Lost merah", () => {
    for (const s of STATUS_PROYEK) expect(statusBadgeClass(s)).not.toBe("");
    for (const s of QUALIFICATION_STATE) expect(qualificationBadgeClass(s)).not.toBe("");
    expect(statusBadgeClass("Lost")).toContain("red");
    expect(statusBadgeClass("tidak-dikenal")).toContain("neutral");
  });
});

describe("aksiStatusTersedia — Submitted dan revisi (SA ditugaskan / Lead_SA / admin)", () => {
  it.each(["Assigned", "In Progress"])("%s: SA utama, SA tambahan, Lead_SA, admin dapat Submitted", (status) => {
    for (const p of [PERAN.saUtama, PERAN.saTambahan, PERAN.lead, PERAN.admin]) {
      expect(kunci(status, p)).toContain("submitted");
    }
  });

  it.each(["Assigned", "In Progress"])("%s: SA lain, Sales PIC, Product PIC tidak dapat Submitted", (status) => {
    for (const p of [PERAN.saLain, PERAN.salesPic, PERAN.productPic]) {
      expect(kunci(status, p)).not.toContain("submitted");
    }
  });

  it("Submitted: revisi (kembali ke In Progress) hanya untuk SA ditugaskan, Lead_SA, admin", () => {
    for (const p of [PERAN.saUtama, PERAN.saTambahan, PERAN.lead, PERAN.admin]) {
      expect(kunci("Submitted", p)).toContain("revisi");
    }
    for (const p of [PERAN.saLain, PERAN.salesPic]) expect(kunci("Submitted", p)).not.toContain("revisi");
    const revisi = aksiStatusTersedia({ actor: PERAN.lead, status: "Submitted" }).find((a) => a.kunci === "revisi");
    expect(revisi).toMatchObject({ newStatus: "In Progress", butuhAlasan: false });
  });

  it("status lain tidak menampilkan Submitted", () => {
    for (const s of ["Intake", "Awaiting Assignment", "Submitted", "Won", "Handed Over", "On Hold", "Closed", "Lost"]) {
      expect(kunci(s, PERAN.lead)).not.toContain("submitted");
    }
  });
});

describe("aksiStatusTersedia — Won (Sales/Product PIC, Lead_SA, admin)", () => {
  it("hanya dari Submitted", () => {
    for (const s of ["Intake", "Awaiting Assignment", "Assigned", "In Progress", "Won", "On Hold"]) {
      expect(kunci(s, PERAN.lead)).not.toContain("won");
    }
  });

  it("Sales PIC, Product PIC, Lead_SA, admin dapat; SA dan Sales non-PIC tidak", () => {
    for (const p of [PERAN.salesPic, PERAN.productPic, PERAN.lead, PERAN.admin]) {
      expect(kunci("Submitted", p)).toContain("won");
    }
    for (const p of [PERAN.saUtama, PERAN.saLain, PERAN.salesLain]) {
      expect(kunci("Submitted", p)).not.toContain("won");
    }
  });

  it("peran Sales dengan id sama dengan SA tetap ditolak bila perannya bukan requester", () => {
    expect(kunci("Submitted", aktor("SA", false, SALES_ID))).not.toContain("won");
  });
});

describe("aksiStatusTersedia — jeda dan lanjut (PIC, Lead_SA, admin)", () => {
  it.each(["Awaiting Assignment", "Assigned", "In Progress", "Submitted"])("%s dapat dijeda oleh PIC/Lead/admin", (s) => {
    for (const p of [PERAN.salesPic, PERAN.productPic, PERAN.lead, PERAN.admin]) {
      expect(kunci(s, p)).toContain("jeda");
    }
    for (const p of [PERAN.saUtama, PERAN.salesLain]) expect(kunci(s, p)).not.toContain("jeda");
  });

  it.each(["Intake", "Won", "Handed Over", "On Hold", "Closed", "Lost"])("%s tidak dapat dijeda", (s) => {
    expect(kunci(s, PERAN.lead)).not.toContain("jeda");
  });

  it("On Hold: lanjut ke previous_status oleh PIC/Lead/admin; SA tidak", () => {
    const ctx = { previousStatus: "In Progress" };
    for (const p of [PERAN.salesPic, PERAN.productPic, PERAN.lead, PERAN.admin]) {
      expect(kunci("On Hold", p, ctx)).toContain("lanjut");
    }
    expect(kunci("On Hold", PERAN.saUtama, ctx)).not.toContain("lanjut");
    const lanjut = aksiStatusTersedia({ actor: PERAN.lead, status: "On Hold", previousStatus: "In Progress" }).find(
      (a) => a.kunci === "lanjut",
    );
    expect(lanjut).toMatchObject({ newStatus: "In Progress", butuhAlasan: false });
  });

  it("On Hold tanpa previous_status: tidak ada tombol lanjut", () => {
    expect(kunci("On Hold", PERAN.lead, { previousStatus: null })).not.toContain("lanjut");
  });
});

describe("aksiStatusTersedia — Lost dan Closed (Lead_SA / admin)", () => {
  it.each(["Intake", "Awaiting Assignment", "Assigned", "In Progress", "Submitted", "Won", "On Hold"])(
    "%s: Lost (alasan wajib) hanya untuk Lead_SA/admin",
    (s) => {
      for (const p of [PERAN.lead, PERAN.admin]) expect(kunci(s, p)).toContain("lost");
      for (const p of [PERAN.saUtama, PERAN.salesPic, PERAN.productPic]) expect(kunci(s, p)).not.toContain("lost");
      const lost = aksiStatusTersedia({ actor: PERAN.lead, status: s }).find((a) => a.kunci === "lost");
      expect(lost).toMatchObject({ newStatus: "Lost", butuhAlasan: true });
    },
  );

  it.each(["Handed Over", "Closed", "Lost"])("%s: tidak ada Lost", (s) => {
    expect(kunci(s, PERAN.lead, { previousStatus: "Won" })).not.toContain("lost");
  });

  it("Closed hanya dari Handed Over dan hanya Lead_SA/admin", () => {
    for (const p of [PERAN.lead, PERAN.admin]) expect(kunci("Handed Over", p)).toContain("closed");
    for (const p of [PERAN.saUtama, PERAN.salesPic]) expect(kunci("Handed Over", p)).not.toContain("closed");
    expect(kunci("Won", PERAN.lead)).not.toContain("closed");
  });
});

describe("aksiStatusTersedia — buka kembali (hanya is_admin, alasan wajib)", () => {
  it.each(["Closed", "Lost"])("%s: hanya admin; Lead_SA non-admin tidak", (s) => {
    const ctx = { previousStatus: "Handed Over" };
    expect(kunci(s, PERAN.admin, ctx)).toEqual(["buka_kembali"]);
    expect(kunci(s, PERAN.lead, ctx)).toEqual([]);
    expect(kunci(s, PERAN.saUtama, ctx)).toEqual([]);
    const a = aksiStatusTersedia({ actor: PERAN.admin, status: s, previousStatus: "Handed Over" })[0];
    expect(a).toMatchObject({ newStatus: "Handed Over", butuhAlasan: true });
  });

  it("tanpa previous_status: tidak ada tombol buka kembali", () => {
    expect(kunci("Closed", PERAN.admin, { previousStatus: null })).toEqual([]);
  });

  it("Closed dan Lost read-only: tidak ada aksi lain bagi admin", () => {
    expect(kunci("Lost", PERAN.admin, { previousStatus: "Submitted" })).toEqual(["buka_kembali"]);
  });
});

describe("aksiStatusTersedia — tanpa aktor", () => {
  it("tidak menampilkan aksi apa pun", () => {
    expect(kunci("Submitted", null)).toEqual([]);
    expect(kunci("Submitted", undefined)).toEqual([]);
  });
});

describe("bisaHandover — hak tombol Handover (cermin TingkatAkses.HANDOVER di backend)", () => {
  const ctx = (actor: KonteksAksi["actor"], status = "Won", saIds: string[] = [SA_ID, SA_TAMBAHAN_ID]) =>
    bisaHandover({ actor, status, saIds });

  it("tampil untuk SA utama, SA tambahan, Lead_SA, dan Admin pada Won", () => {
    expect(ctx(PERAN.saUtama)).toBe(true);
    expect(ctx(PERAN.saTambahan)).toBe(true);
    expect(ctx(PERAN.lead)).toBe(true);
    expect(ctx(PERAN.admin)).toBe(true);
  });

  it("tidak tampil untuk SA yang tidak ditugaskan, Sales/Product (termasuk PIC), dan tanpa aktor", () => {
    expect(ctx(PERAN.saLain)).toBe(false);
    expect(ctx(PERAN.salesPic)).toBe(false);
    expect(ctx(PERAN.productPic)).toBe(false);
    expect(ctx(PERAN.salesLain)).toBe(false);
    expect(ctx(null)).toBe(false);
    expect(ctx(undefined)).toBe(false);
  });

  it.each(STATUS_PROYEK.filter((s) => s !== "Won"))("tidak tampil pada status %s", (status) => {
    expect(ctx(PERAN.lead, status)).toBe(false);
    expect(ctx(PERAN.saUtama, status)).toBe(false);
  });
});
