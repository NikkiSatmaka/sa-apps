import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, errorEnvelope, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { ProjectComments } from "./ProjectComments";

interface Komentar {
  id_comment: string;
  id_project: string;
  author_id: string;
  author_name: string | null;
  author_role: string | null;
  body: string;
  created_at: string;
}

function makeKomentar(o: Partial<Komentar> = {}): Komentar {
  return {
    id_comment: "CMT-1",
    id_project: "p1",
    author_id: "u1",
    author_name: "Sales Demo",
    author_role: "Sales",
    body: "Mohon cek BOQ",
    created_at: "2030-01-05T09:30:00Z",
    ...o,
  };
}

function serve(items: Komentar[]) {
  server.use(http.get(api("/projects/p1/comments"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))));
}

function setup(role: Role = "SA", readOnly = false) {
  return renderWithProviders(<ProjectComments projectId="p1" readOnly={readOnly} />, { role });
}

describe("ProjectComments — daftar", () => {
  it("menampilkan komentar berurutan dengan nama dan peran penulis", async () => {
    serve([makeKomentar(), makeKomentar({ id_comment: "CMT-2", author_name: "SA Demo", author_role: "SA", body: "Sudah dicek" })]);
    setup();
    expect(await screen.findByText("Mohon cek BOQ")).toBeInTheDocument();
    expect(screen.getByText("Sudah dicek")).toBeInTheDocument();
    expect(screen.getByText("Sales Demo")).toBeInTheDocument();
    expect(screen.getByText("SA Demo")).toBeInTheDocument();
    const isi = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(isi[0]).toContain("Mohon cek BOQ");
    expect(isi[1]).toContain("Sudah dicek");
  });

  it("menjaga baris baru pada isi komentar", async () => {
    serve([makeKomentar({ body: "Baris 1\nBaris 2" })]);
    setup();
    const el = await screen.findByText(/Baris 1/);
    expect(el.className).toMatch(/whitespace-pre-wrap/);
  });

  it("keadaan kosong", async () => {
    serve([]);
    setup();
    expect(await screen.findByText("Belum ada komentar.")).toBeInTheDocument();
  });

  it("error memuat tampil sebagai alert yang bisa dicoba ulang, bukan keadaan kosong", async () => {
    server.use(gagalLaluBerhasil("/projects/p1/comments", { items: [makeKomentar()], total: 1 }));
    const { user } = setup();
    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat komentar.");
    expect(screen.queryByText("Belum ada komentar.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByText("Mohon cek BOQ")).toBeInTheDocument();
  });

  it("dapat dibaca semua peran", async () => {
    serve([makeKomentar()]);
    for (const role of ["Sales", "Product", "SA", "Lead_SA", "Admin"] as const) {
      const { unmount } = setup(role);
      expect(await screen.findByText("Mohon cek BOQ")).toBeInTheDocument();
      unmount();
    }
  });
});

describe("ProjectComments — menulis", () => {
  it("mengirim isi ter-trim, mengosongkan form, dan memuat ulang thread", async () => {
    let items: Komentar[] = [];
    let body: unknown;
    server.use(
      http.get(api("/projects/p1/comments"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))),
      http.post(api("/projects/p1/comments"), async ({ request }) => {
        body = await request.json();
        items = [makeKomentar({ body: "Halo tim" })];
        return HttpResponse.json(successEnvelope(items[0]), { status: 201 });
      }),
    );
    const { user } = setup("Sales");
    await screen.findByText("Belum ada komentar.");
    await user.type(screen.getByLabelText("Tulis komentar"), "  Halo tim  ");
    await user.click(screen.getByRole("button", { name: "Kirim" }));
    expect(await screen.findByText("Halo tim")).toBeInTheDocument();
    expect(body).toEqual({ body: "Halo tim" });
    expect(screen.getByLabelText("Tulis komentar")).toHaveValue("");
  });

  it("tombol Kirim nonaktif bila isi kosong atau hanya spasi", async () => {
    serve([]);
    const { user } = setup();
    await screen.findByText("Belum ada komentar.");
    expect(screen.getByRole("button", { name: "Kirim" })).toBeDisabled();
    await user.type(screen.getByLabelText("Tulis komentar"), "   ");
    expect(screen.getByRole("button", { name: "Kirim" })).toBeDisabled();
  });

  it("membatasi panjang isi 4000 karakter", async () => {
    serve([]);
    setup();
    await screen.findByText("Belum ada komentar.");
    expect(screen.getByLabelText("Tulis komentar")).toHaveAttribute("maxlength", "4000");
  });

  it("menampilkan penolakan server (403) apa adanya dan mempertahankan isian", async () => {
    serve([]);
    server.use(http.post(api("/projects/p1/comments"), () => HttpResponse.json(errorEnvelope("Anda tidak memiliki akses ke proyek ini."), { status: 403 })));
    const { user } = setup("Sales");
    await screen.findByText("Belum ada komentar.");
    await user.type(screen.getByLabelText("Tulis komentar"), "Halo");
    await user.click(screen.getByRole("button", { name: "Kirim" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Anda tidak memiliki akses ke proyek ini.");
    expect(screen.getByLabelText("Tulis komentar")).toHaveValue("Halo");
  });

  it("proyek read-only: thread tetap tampil, form diganti keterangan", async () => {
    serve([makeKomentar()]);
    setup("Admin", true);
    expect(await screen.findByText("Mohon cek BOQ")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tulis komentar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kirim" })).not.toBeInTheDocument();
    expect(screen.getByText(/Proyek berstatus Closed atau Lost: komentar baru tidak dapat ditambahkan/)).toBeInTheDocument();
  });
});
