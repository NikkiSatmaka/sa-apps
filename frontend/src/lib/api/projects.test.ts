import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, successEnvelope, errorEnvelope } from "@/test";
import { makeCreateProjectResponse } from "@/test/fixtures/projects";
import { makeQualificationSchema, makeQuestion } from "@/test/fixtures/qualification";
import { ApiError } from "../fetcher";
import { createProject, extractFieldErrors, getBANTResult, updateQualificationAnswers } from "./projects";

describe("extractFieldErrors", () => {
  it("mengambil daftar {field, reason} dari ApiError 422", () => {
    const err = new ApiError("Validasi", 422, { data: [{ field: "email", reason: "Format salah" }] });
    expect(extractFieldErrors(err)).toEqual([{ field: "email", reason: "Format salah" }]);
  });

  it("membuang entri yang bentuknya tidak valid", () => {
    const err = new ApiError("x", 422, { data: [{ field: "a", reason: "ok" }, { field: 1, reason: "x" }, null, { field: "b" }] });
    expect(extractFieldErrors(err)).toEqual([{ field: "a", reason: "ok" }]);
  });

  it.each([null, undefined, "teks", {}, { data: null }, { data: { data: "bukan array" } }, new Error("x")])(
    "mengembalikan [] untuk masukan tak sesuai: %s",
    (input) => {
      expect(extractFieldErrors(input)).toEqual([]);
    }
  );
});

describe("createProject", () => {
  it("mengirim multipart tanpa Content-Type manual (boundary dari browser) dan token", async () => {
    localStorage.setItem("access_token", "tok");
    let contentType: string | null = null;
    let auth: string | null = null;
    let nama: FormDataEntryValue | null = null;
    server.use(
      http.post(api("/projects"), async ({ request }) => {
        contentType = request.headers.get("Content-Type");
        auth = request.headers.get("Authorization");
        nama = (await request.formData()).get("project_name");
        return HttpResponse.json(successEnvelope(makeCreateProjectResponse()), { status: 201 });
      })
    );
    const fd = new FormData();
    fd.append("project_name", "Proyek A");

    const res = await createProject(fd);

    expect(contentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(auth).toBe("Bearer tok");
    expect(nama).toBe("Proyek A");
    expect(res).toMatchObject({ scoring_triggered: expect.any(Boolean) });
  });

  it("tanpa token tidak mengirim Authorization", async () => {
    let auth: string | null = "x";
    server.use(
      http.post(api("/projects"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(makeCreateProjectResponse()), { status: 201 });
      })
    );
    await createProject(new FormData());
    expect(auth).toBeNull();
  });

  it("422: ApiError menyimpan error per field yang bisa diekstrak", async () => {
    server.use(
      http.post(api("/projects"), () =>
        HttpResponse.json({ status: "error", message: "Validasi gagal", data: [{ field: "customer_name", reason: "Wajib diisi" }] }, { status: 422 })
      )
    );
    const err = await createProject(new FormData()).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, message: "Validasi gagal" });
    expect(extractFieldErrors(err)).toEqual([{ field: "customer_name", reason: "Wajib diisi" }]);
  });

  it("error tanpa JSON memakai pesan bawaan", async () => {
    server.use(http.post(api("/projects"), () => new HttpResponse("x", { status: 500 })));
    await expect(createProject(new FormData())).rejects.toMatchObject({ message: "Gagal membuat proyek (status 500)" });
  });
});

describe("getBANTResult", () => {
  it("mengembalikan hasil BANT", async () => {
    await expect(getBANTResult("p1")).resolves.toMatchObject({ bant_score: 80, status: "Awaiting Assignment" });
  });

  it("404 berarti belum ada hasil → null", async () => {
    server.use(http.get(api("/projects/:id/bant-result"), () => HttpResponse.json(errorEnvelope("Belum ada"), { status: 404 })));
    await expect(getBANTResult("p1")).resolves.toBeNull();
  });

  it("status error lain dilempar", async () => {
    server.use(http.get(api("/projects/:id/bant-result"), () => HttpResponse.json(errorEnvelope("Server error"), { status: 500 })));
    await expect(getBANTResult("p1")).rejects.toMatchObject({ status: 500, message: "Server error" });
  });

  it("pesan bawaan saat body bukan JSON", async () => {
    server.use(http.get(api("/projects/:id/bant-result"), () => new HttpResponse("x", { status: 500 })));
    await expect(getBANTResult("p1")).rejects.toMatchObject({ message: "Gagal mengambil hasil BANT (status 500)" });
  });

  it("menyertakan Bearer token bila ada", async () => {
    localStorage.setItem("access_token", "tok");
    let auth: string | null = null;
    server.use(
      http.get(api("/projects/:id/bant-result"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope({}));
      })
    );
    await getBANTResult("p1");
    expect(auth).toBe("Bearer tok");
  });
});

describe("updateQualificationAnswers", () => {
  const schema = makeQualificationSchema({
    questions: [
      makeQuestion({ name: "budget_range", required: true }),
      makeQuestion({ name: "jumlah", type: "number" }),
      makeQuestion({ name: "catatan", required: false }),
    ],
  });

  it("PUT payload dari skema: angka jadi number, kosong jadi null", async () => {
    let body: unknown;
    let method = "";
    server.use(
      http.put(api("/projects/:id/qualification-answers"), async ({ request }) => {
        body = await request.json();
        method = request.method;
        return HttpResponse.json(successEnvelope({ total_score: 90, status: "Awaiting Assignment", rescored: true }));
      })
    );
    const res = await updateQualificationAnswers("p1", schema, { budget_range: " 100 juta ", jumlah: "12", catatan: "" });
    expect(method).toBe("PUT");
    expect(body).toEqual({ budget_range: "100 juta", jumlah: 12, catatan: null });
    expect(res).toMatchObject({ total_score: 90, rescored: true });
  });

  it("menolak dengan pesan backend (mis. status terkunci)", async () => {
    server.use(http.put(api("/projects/:id/qualification-answers"), () => HttpResponse.json(errorEnvelope("Status terkunci"), { status: 409 })));
    await expect(updateQualificationAnswers("p1", schema, {})).rejects.toMatchObject({ status: 409, message: "Status terkunci" });
  });
});
