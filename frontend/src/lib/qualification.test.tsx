import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { http, HttpResponse, server, api, errorEnvelope, successEnvelope } from "@/test";
import { makeQualificationSchema, makeQuestion } from "@/test/fixtures/qualification";
import {
  answerEditMode,
  answerQuestions,
  answersFromView,
  EDITABLE_STATUS,
  layoutRows,
  toPayload,
  useQualificationSchema,
  validateAnswers,
} from "./qualification";

const schema = makeQualificationSchema({
  groups: [
    { key: "budget", title: "Budget" },
    { key: "authority", title: "Authority" },
  ],
  questions: [
    makeQuestion({ name: "proyek", group: "budget", header: true, required: true }),
    makeQuestion({ name: "anggaran", group: "budget", type: "number", min_value: 10, max_value: 100, required: true }),
    makeQuestion({ name: "mata_uang", group: "budget", type: "choice", choices: ["IDR", "USD"], required: false }),
    makeQuestion({ name: "nama_pic", group: "authority", row: "pic", row_hint: "Isi data PIC", required: true, max_length: 5 }),
    makeQuestion({ name: "email_pic", group: "authority", type: "email", row: "pic", pattern: "^\\S+@\\S+$", required: false }),
    makeQuestion({ name: "jabatan", group: "authority", row: "pic", row_hint: "tidak dipakai", required: false, pattern: "^[A-Z]+$", type: "short" }),
    makeQuestion({ name: "catatan", group: "authority", required: false, max_length: null }),
  ],
});

describe("useQualificationSchema", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>{children}</SWRConfig>
  );

  it("memuat → sukses: skema dari backend", async () => {
    const { result } = renderHook(() => useQualificationSchema(), { wrapper });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.schema).toBeUndefined();

    await waitFor(() => expect(result.current.schema).toBeDefined());
    expect(result.current.schema?.schema_version).toBe(1);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeUndefined();
  });

  it("respons error: error terisi dan skema kosong", async () => {
    server.use(http.get(api("/qualification/schema"), () => HttpResponse.json(errorEnvelope("Skema hilang"), { status: 500 })));
    const { result } = renderHook(() => useQualificationSchema(), { wrapper });
    await waitFor(() => expect(result.current.error).toBeDefined());
    expect(result.current.error).toMatchObject({ status: 500, message: "Skema hilang" });
    expect(result.current.schema).toBeUndefined();
  });

  it("mengambil skema yang dikembalikan handler (bukan nilai tertanam)", async () => {
    server.use(http.get(api("/qualification/schema"), () => HttpResponse.json(successEnvelope(makeQualificationSchema({ schema_version: 7 })))));
    const { result } = renderHook(() => useQualificationSchema(), { wrapper });
    await waitFor(() => expect(result.current.schema?.schema_version).toBe(7));
  });
});

describe("answerQuestions", () => {
  it("membuang field header", () => {
    expect(answerQuestions(schema).map((q) => q.name)).not.toContain("proyek");
    expect(answerQuestions(schema)).toHaveLength(6);
  });
});

describe("layoutRows", () => {
  it("mengelompokkan pertanyaan berurutan ber-row sama dalam satu baris; hint dari anggota pertama yang punya", () => {
    const rows = layoutRows(schema, "authority");
    expect(rows).toHaveLength(2);
    expect(rows[0].questions.map((q) => q.name)).toEqual(["nama_pic", "email_pic", "jabatan"]);
    expect(rows[0].hint).toBe("Isi data PIC");
    expect(rows[1].questions.map((q) => q.name)).toEqual(["catatan"]);
  });

  it("hanya memuat grup yang diminta, tanpa header; grup tak dikenal → kosong", () => {
    expect(layoutRows(schema, "budget").map((r) => r.questions[0].name)).toEqual(["anggaran", "mata_uang"]);
    expect(layoutRows(schema, "tidak-ada")).toEqual([]);
  });

  it("row sama tapi tidak berurutan tidak digabung", () => {
    const s = makeQualificationSchema({
      groups: [{ key: "g", title: "G" }],
      questions: [
        makeQuestion({ name: "a", group: "g", row: "r" }),
        makeQuestion({ name: "b", group: "g", row: null }),
        makeQuestion({ name: "c", group: "g", row: "r" }),
      ],
    });
    expect(layoutRows(s, "g").map((r) => r.questions.map((q) => q.name))).toEqual([["a"], ["b"], ["c"]]);
  });

  it("hint baris diisi dari anggota berikutnya bila anggota pertama tidak punya", () => {
    const s = makeQualificationSchema({
      questions: [
        makeQuestion({ name: "a", row: "r", row_hint: null }),
        makeQuestion({ name: "b", row: "r", row_hint: "dari b" }),
      ],
    });
    expect(layoutRows(s, "budget")[0].hint).toBe("dari b");
  });
});

describe("validateAnswers", () => {
  const valid = { anggaran: "50", mata_uang: "IDR", nama_pic: "Budi", email_pic: "a@b.c", jabatan: "CTO", catatan: "" };

  it("jawaban valid → tanpa error", () => {
    expect(validateAnswers(schema, valid)).toEqual({});
  });

  it("wajib diisi; spasi saja dianggap kosong; opsional boleh kosong; header diabaikan", () => {
    const e = validateAnswers(schema, { anggaran: "  ", nama_pic: "" });
    expect(e).toEqual({ anggaran: "Wajib diisi", nama_pic: "Wajib diisi" });
    expect(e.proyek).toBeUndefined();
  });

  it("angka: bukan angka, di bawah min, di atas max", () => {
    expect(validateAnswers(schema, { ...valid, anggaran: "abc" }).anggaran).toBe("Harus berupa angka");
    expect(validateAnswers(schema, { ...valid, anggaran: "5" }).anggaran).toBe("Harus antara 10 dan 100");
    expect(validateAnswers(schema, { ...valid, anggaran: "101" }).anggaran).toBe("Harus antara 10 dan 100");
    expect(validateAnswers(schema, { ...valid, anggaran: "10" }).anggaran).toBeUndefined();
    expect(validateAnswers(schema, { ...valid, anggaran: "100" }).anggaran).toBeUndefined();
  });

  it("angka dengan batas sebelah: pesan memakai ∞", () => {
    const s = makeQualificationSchema({ questions: [makeQuestion({ name: "n", type: "number", min_value: 1, max_value: null, required: false })] });
    expect(validateAnswers(s, { n: "0" }).n).toBe("Harus antara 1 dan ∞");
    const s2 = makeQualificationSchema({ questions: [makeQuestion({ name: "n", type: "number", min_value: null, max_value: 5, required: false })] });
    expect(validateAnswers(s2, { n: "6" }).n).toBe("Harus antara -∞ dan 5");
    expect(validateAnswers(s2, { n: "-999" }).n).toBeUndefined();
  });

  it("pilihan di luar daftar ditolak; choices null ditolak", () => {
    expect(validateAnswers(schema, { ...valid, mata_uang: "EUR" }).mata_uang).toBe("Pilihan tidak valid");
    const s = makeQualificationSchema({ questions: [makeQuestion({ name: "c", type: "choice", choices: null, required: false })] });
    expect(validateAnswers(s, { c: "x" }).c).toBe("Pilihan tidak valid");
  });

  it("teks: panjang maksimum, pola, dan pesan khusus email", () => {
    expect(validateAnswers(schema, { ...valid, nama_pic: "Terlalu panjang" }).nama_pic).toBe("Maksimal 5 karakter");
    expect(validateAnswers(schema, { ...valid, email_pic: "tanpa-at" }).email_pic).toBe("Format email tidak valid");
    expect(validateAnswers(schema, { ...valid, jabatan: "kecil" }).jabatan).toBe("Format tidak valid");
  });

  it("nilai di-trim sebelum divalidasi", () => {
    expect(validateAnswers(schema, { ...valid, anggaran: " 50 ", nama_pic: " Budi " })).toEqual({});
  });
});

describe("toPayload", () => {
  it("kosong → null, number → angka, teks di-trim, header tidak dikirim", () => {
    expect(toPayload(schema, { anggaran: " 42 ", mata_uang: "", nama_pic: " Budi ", proyek: "X" })).toEqual({
      anggaran: 42,
      mata_uang: null,
      nama_pic: "Budi",
      email_pic: null,
      jabatan: null,
      catatan: null,
    });
  });
});

describe("answersFromView", () => {
  it("mengubah nilai backend menjadi string form; null/tidak ada → ''", () => {
    expect(answersFromView(schema, { anggaran: 50, nama_pic: "Budi", mata_uang: null })).toEqual({
      anggaran: "50",
      mata_uang: "",
      nama_pic: "Budi",
      email_pic: "",
      jabatan: "",
      catatan: "",
    });
  });

  it("answers null → semua kosong", () => {
    const out = answersFromView(schema, null);
    expect(Object.values(out).every((v) => v === "")).toBe(true);
    expect(Object.keys(out)).toHaveLength(6);
  });

  it("round-trip dengan toPayload mempertahankan nilai", () => {
    const form = answersFromView(schema, { anggaran: 50, nama_pic: "Budi" });
    expect(toPayload(schema, form)).toMatchObject({ anggaran: 50, nama_pic: "Budi", jabatan: null });
  });
});

describe("answerEditMode", () => {
  /** Pengguna dengan role fungsional + flag admin (ADR 0012). */
  const pengguna = (role: string | undefined, id: string | undefined, is_admin = false) => ({ role, id, is_admin });
  const admin = pengguna("SA", "x", true);

  it.each(["Sales", "Product"])("%s PIC pada Need Clarification → rescore", (role) => {
    expect(answerEditMode(pengguna(role, "u1"), "u1", EDITABLE_STATUS)).toBe("rescore");
  });

  it.each([pengguna("Lead_SA", "x"), admin])("%j pada Need Clarification → rescore", (user) => {
    expect(answerEditMode(user, "u1", EDITABLE_STATUS)).toBe("rescore");
  });

  it.each(["Sales", "Product"])("%s PIC di status lain → none (tidak boleh koreksi)", (role) => {
    expect(answerEditMode(pengguna(role, "u1"), "u1", "Pending Assignment")).toBe("none");
  });

  it("Product PIC (di antara beberapa PIC project) pada Need Clarification → rescore", () => {
    expect(answerEditMode(pengguna("Product", "p1"), ["s1", "p1"], EDITABLE_STATUS)).toBe("rescore");
    expect(answerEditMode(pengguna("Sales", "s1"), ["s1", null], EDITABLE_STATUS)).toBe("rescore");
  });

  it("pembuat yang bukan PIC (tidak ada di daftar PIC) → none", () => {
    expect(answerEditMode(pengguna("Sales", "u9"), ["s1", "p1"], EDITABLE_STATUS)).toBe("none");
    expect(answerEditMode(pengguna("Product", "u9"), [null, undefined], EDITABLE_STATUS)).toBe("none");
  });

  it.each(["Sales", "Product"])("%s bukan PIC → none, termasuk saat userId/PIC tidak ada", (role) => {
    expect(answerEditMode(pengguna(role, "u2"), "u1", EDITABLE_STATUS)).toBe("none");
    expect(answerEditMode(pengguna(role, undefined), undefined, EDITABLE_STATUS)).toBe("none");
    expect(answerEditMode(pengguna(role, "u1"), null, EDITABLE_STATUS)).toBe("none");
  });

  it.each([pengguna("SA", "u1"), pengguna(undefined, "u1")])("%j → none", (user) => {
    expect(answerEditMode(user, "u1", EDITABLE_STATUS)).toBe("none");
  });

  it("tanpa user → none", () => {
    expect(answerEditMode(null, "u1", EDITABLE_STATUS)).toBe("none");
  });

  it.each([pengguna("Lead_SA", "x"), admin])("%j setelah lolos gate → correct", (user) => {
    expect(answerEditMode(user, "u1", "Pending Assignment")).toBe("correct");
    expect(answerEditMode(user, "u1", "Closed Win")).toBe("correct");
  });

  it.each(["New", "Scoring Pending", "Manual Review Required"])("Lead_SA pada status terkunci %s → none", (status) => {
    expect(answerEditMode(pengguna("Lead_SA", "x"), "u1", status)).toBe("none");
  });
});
