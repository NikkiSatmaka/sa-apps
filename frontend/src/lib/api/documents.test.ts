import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, successEnvelope, errorEnvelope } from "@/test";
import { makeDocument } from "@/test/fixtures/documents";
import {
  addRequirementItem,
  createDocument,
  deleteRequirementItem,
  getProjectDocuments,
  getRequirementStatus,
  getSolutionsDocuments,
  keepRequirementVersion,
  regenerateRequirement,
  updateDQNumber,
  updateDocumentStatus,
  updateRequirementItem,
} from "./documents";

const gagal = (status: number, message?: string) =>
  message ? HttpResponse.json(errorEnvelope(message), { status }) : new HttpResponse("x", { status });

describe("getProjectDocuments", () => {
  it("mengambil array dari data.documents", async () => {
    const docs = await getProjectDocuments("p1");
    expect(docs).toHaveLength(1);
    expect(docs[0]).toMatchObject({ doc_type: "BOQ" });
  });

  it("keadaan kosong: data tanpa documents → []", async () => {
    server.use(http.get(api("/projects/:id/documents"), () => HttpResponse.json(successEnvelope({}))));
    await expect(getProjectDocuments("p1")).resolves.toEqual([]);
  });

  it("error: pesan backend dan pesan bawaan", async () => {
    server.use(http.get(api("/projects/:id/documents"), () => gagal(404, "Proyek tidak ada")));
    await expect(getProjectDocuments("p1")).rejects.toMatchObject({ status: 404, message: "Proyek tidak ada" });
    server.use(http.get(api("/projects/:id/documents"), () => gagal(500)));
    await expect(getProjectDocuments("p1")).rejects.toMatchObject({ message: "Gagal mengambil daftar dokumen (status 500)" });
  });

  it("mengirim Bearer token bila ada", async () => {
    localStorage.setItem("access_token", "tok");
    let auth: string | null = null;
    server.use(
      http.get(api("/projects/:id/documents"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope({ documents: [] }));
      })
    );
    await getProjectDocuments("p1");
    expect(auth).toBe("Bearer tok");
  });
});

describe("createDocument", () => {
  it("mem-POST input dokumen dan mengembalikan dokumen", async () => {
    let body: unknown;
    server.use(
      http.post(api("/projects/:id/documents"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(makeDocument({ doc_type: "HLD" })), { status: 201 });
      })
    );
    const input = { doc_type: "HLD" as const, gdrive_link: "https://drive.google.com/x", folder_type: "Solutions" as const, notes: "n" };
    await expect(createDocument("p1", input)).resolves.toMatchObject({ doc_type: "HLD" });
    expect(body).toEqual(input);
  });

  it("error: pesan backend dan pesan bawaan", async () => {
    server.use(http.post(api("/projects/:id/documents"), () => gagal(422, "Link tidak valid")));
    await expect(createDocument("p1", { doc_type: "BOQ", gdrive_link: "x", folder_type: "Solutions" })).rejects.toMatchObject({
      status: 422,
      message: "Link tidak valid",
    });
    server.use(http.post(api("/projects/:id/documents"), () => gagal(500)));
    await expect(createDocument("p1", { doc_type: "BOQ", gdrive_link: "x", folder_type: "Solutions" })).rejects.toMatchObject({
      message: "Gagal membuat dokumen (status 500)",
    });
  });
});

describe("updateDocumentStatus", () => {
  it("PATCH new_status dan mengembalikan dokumen terbaru", async () => {
    let body: unknown;
    server.use(
      http.patch(api("/documents/:id/status"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(makeDocument({ status: "Final" })));
      })
    );
    await expect(updateDocumentStatus("d1", "Final")).resolves.toMatchObject({ status: "Final" });
    expect(body).toEqual({ new_status: "Final" });
  });

  it("error transisi tidak valid", async () => {
    server.use(http.patch(api("/documents/:id/status"), () => gagal(400, "Transisi tidak valid")));
    await expect(updateDocumentStatus("d1", "Final")).rejects.toMatchObject({ status: 400, message: "Transisi tidak valid" });
    server.use(http.patch(api("/documents/:id/status"), () => gagal(500)));
    await expect(updateDocumentStatus("d1", "Final")).rejects.toMatchObject({ message: "Gagal mengubah status dokumen (status 500)" });
  });
});

describe("updateDQNumber", () => {
  it("PATCH dq_number", async () => {
    let body: unknown;
    server.use(
      http.patch(api("/projects/:id/dq-number"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope({ id_project: "p1", dq_number: "DQ-99999", status: "Active" }));
      })
    );
    await expect(updateDQNumber("p1", "DQ-99999")).resolves.toMatchObject({ dq_number: "DQ-99999" });
    expect(body).toEqual({ dq_number: "DQ-99999" });
  });

  it("error format DQ", async () => {
    server.use(http.patch(api("/projects/:id/dq-number"), () => gagal(422, "Format DQ salah")));
    await expect(updateDQNumber("p1", "x")).rejects.toMatchObject({ status: 422, message: "Format DQ salah" });
    server.use(http.patch(api("/projects/:id/dq-number"), () => gagal(500)));
    await expect(updateDQNumber("p1", "x")).rejects.toMatchObject({ message: "Gagal menyimpan DQ Number (status 500)" });
  });
});

describe("getSolutionsDocuments", () => {
  it("gating DQ: link null dipertahankan apa adanya", async () => {
    server.use(
      http.get(api("/projects/:id/documents/solutions"), () =>
        HttpResponse.json(successEnvelope([makeDocument({ gdrive_link: null })]))
      )
    );
    const docs = await getSolutionsDocuments("p1");
    expect(docs[0].gdrive_link).toBeNull();
  });

  it("kosong dan error", async () => {
    await expect(getSolutionsDocuments("p1")).resolves.toEqual([]);
    server.use(http.get(api("/projects/:id/documents/solutions"), () => gagal(403, "Dilarang")));
    await expect(getSolutionsDocuments("p1")).rejects.toMatchObject({ status: 403, message: "Dilarang" });
    server.use(http.get(api("/projects/:id/documents/solutions"), () => gagal(500)));
    await expect(getSolutionsDocuments("p1")).rejects.toMatchObject({ message: "Gagal mengambil dokumen Solutions (status 500)" });
  });
});

describe("getRequirementStatus", () => {
  it("memetakan status generate dan hak generate ulang", async () => {
    server.use(
      http.get(api("/projects/:id/documents"), () =>
        HttpResponse.json(successEnvelope({ documents: [], requirement_generation_status: "pending", can_regenerate_requirement: true }))
      )
    );
    await expect(getRequirementStatus("p1")).resolves.toEqual({
      requirement_generation_status: "pending",
      can_regenerate_requirement: true,
    });
  });

  it("default: status null dan tidak boleh generate ulang bila field tidak ada", async () => {
    server.use(http.get(api("/projects/:id/documents"), () => HttpResponse.json({ status: "success" })));
    await expect(getRequirementStatus("p1")).resolves.toEqual({
      requirement_generation_status: null,
      can_regenerate_requirement: false,
    });
  });

  it("error", async () => {
    server.use(http.get(api("/projects/:id/documents"), () => gagal(500, "Gagal")));
    await expect(getRequirementStatus("p1")).rejects.toMatchObject({ message: "Gagal" });
    server.use(http.get(api("/projects/:id/documents"), () => gagal(500)));
    await expect(getRequirementStatus("p1")).rejects.toMatchObject({ message: "Gagal mengambil status Requirement (status 500)" });
  });
});

describe.each([
  ["regenerateRequirement", (id: string) => regenerateRequirement(id), "/projects/:id/requirement/regenerate", "Gagal memulai generate ulang (status 500)"],
  ["keepRequirementVersion", (id: string) => keepRequirementVersion(id), "/projects/:id/requirement/keep-version", "Gagal mempertahankan versi Requirement (status 500)"],
])("%s", (_nama, fn, path, pesanBawaan) => {
  it("mem-POST dan selesai tanpa nilai", async () => {
    localStorage.setItem("access_token", "tok");
    let method = "";
    let auth: string | null = null;
    server.use(
      http.post(api(path), ({ request }) => {
        method = request.method;
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(null));
      })
    );
    await expect(fn("p1")).resolves.toBeUndefined();
    expect(method).toBe("POST");
    expect(auth).toBe("Bearer tok");
  });

  it("error: mengutamakan `detail`, lalu `message`, lalu pesan bawaan", async () => {
    server.use(http.post(api(path), () => HttpResponse.json({ detail: "Sedang diproses", message: "m" }, { status: 409 })));
    await expect(fn("p1")).rejects.toMatchObject({ status: 409, message: "Sedang diproses" });
    server.use(http.post(api(path), () => gagal(403, "Dilarang")));
    await expect(fn("p1")).rejects.toMatchObject({ message: "Dilarang" });
    server.use(http.post(api(path), () => gagal(500)));
    await expect(fn("p1")).rejects.toMatchObject({ message: pesanBawaan });
  });
});

describe("butir Requirement", () => {
  const input = { kategori: "Teknis" as const, butir: "Harus HA" };

  it("addRequirementItem: POST ke /requirement/items dengan body", async () => {
    let body: unknown;
    let path = "";
    server.use(
      http.post(api("/projects/:id/requirement/items"), async ({ request }) => {
        body = await request.json();
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope(makeDocument({ is_overridden: true })));
      })
    );
    await expect(addRequirementItem("p1", input)).resolves.toMatchObject({ is_overridden: true });
    expect(body).toEqual(input);
    expect(path).toMatch(/\/projects\/p1\/requirement\/items$/);
  });

  it("updateRequirementItem: PUT ke item tertentu", async () => {
    let body: unknown;
    let path = "";
    server.use(
      http.put(api("/projects/:id/requirement/items/:itemId"), async ({ request }) => {
        body = await request.json();
        path = new URL(request.url).pathname;
        return HttpResponse.json(successEnvelope(makeDocument()));
      })
    );
    await updateRequirementItem("p1", "it-3", input);
    expect(body).toEqual(input);
    expect(path).toMatch(/\/requirement\/items\/it-3$/);
  });

  it("deleteRequirementItem: DELETE tanpa body", async () => {
    let text = "x";
    let method = "";
    server.use(
      http.delete(api("/projects/:id/requirement/items/:itemId"), async ({ request }) => {
        text = await request.text();
        method = request.method;
        return HttpResponse.json(successEnvelope(makeDocument()));
      })
    );
    await deleteRequirementItem("p1", "it-3");
    expect(method).toBe("DELETE");
    expect(text).toBe("");
  });

  it("error: mengutamakan message, lalu detail, lalu pesan bawaan", async () => {
    server.use(http.post(api("/projects/:id/requirement/items"), () => gagal(422, "Butir kosong")));
    await expect(addRequirementItem("p1", input)).rejects.toMatchObject({ status: 422, message: "Butir kosong" });
    server.use(http.post(api("/projects/:id/requirement/items"), () => HttpResponse.json({ detail: ["salah"] }, { status: 422 })));
    await expect(addRequirementItem("p1", input)).rejects.toMatchObject({ message: "salah" });
    server.use(http.post(api("/projects/:id/requirement/items"), () => gagal(500)));
    await expect(addRequirementItem("p1", input)).rejects.toMatchObject({ message: "Gagal menyimpan butir Requirement (status 500)" });
  });
});
