import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";
import type { Document } from "@/lib/api/documents";
import {
  api,
  errorEnvelope,
  http,
  HttpResponse,
  pasangHubungan,
  renderWithProviders,
  seedAuth,
  server,
  setParams,
  successEnvelope,
  type Hubungan,
  type Role,
} from "@/test";
import { users } from "@/test/fixtures/users";
import { makeDocument } from "@/test/fixtures/documents";
import { makeDocumentsData, makeRequirementDoc } from "@/test/fixtures/requirement";
import DocumentsPage from "./page";

const PID = "proj-1";

interface Backend {
  documents: Document[];
  status: "pending" | "ready" | "failed" | null;
  canRegenerate: boolean;
  project: Record<string, unknown> | null;
  listHits: number;
  requests: string[];
}

/** Backend palsu stateful untuk halaman dokumen; dapat diubah di tengah test. */
function mockBackend(init: Partial<Backend> = {}): Backend {
  const be: Backend = {
    documents: [],
    status: null,
    canRegenerate: false,
    project: {
      id_project: PID,
      project_name: "Proyek Alfa",
      customer_name: "PT Beta",
      status: "Documenting",
      dq_number: "DQ-12345",
      use_case_tags: [],
      assigned_sa: { id: users.SA.id },
    },
    listHits: 0,
    requests: [],
    ...init,
  };
  server.use(
    http.get(api("/projects/:id/documents"), () => {
      be.listHits += 1;
      return HttpResponse.json(
        successEnvelope(
          makeDocumentsData(be.documents, {
            requirement_generation_status: be.status,
            can_regenerate_requirement: be.canRegenerate,
          })
        )
      );
    }),
    http.get(api("/projects/:id"), () =>
      be.project
        ? HttpResponse.json(successEnvelope(be.project))
        : HttpResponse.json(errorEnvelope("Tidak ada"), { status: 404 })
    ),
    http.post(api("/projects/:id/documents"), async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      be.requests.push(`POST documents ${JSON.stringify(body)}`);
      be.documents = [...be.documents, makeDocument({ id_doc: "new-1", ...(body as Partial<Document>) })];
      return HttpResponse.json(successEnvelope(be.documents.at(-1)), { status: 201 });
    }),
    http.patch(api("/documents/:docId/status"), async ({ params, request }) => {
      const body = (await request.json()) as { new_status: Document["status"] };
      be.requests.push(`PATCH status ${params.docId} ${body.new_status}`);
      be.documents = be.documents.map((d) => (d.id_doc === params.docId ? { ...d, status: body.new_status } : d));
      return HttpResponse.json(successEnvelope(be.documents[0]));
    })
  );
  return be;
}

function renderPage(role: Role) {
  setParams({ id: PID });
  return renderWithProviders(<DocumentsPage />, { role });
}

async function loaded() {
  await screen.findByRole("table", { name: "Daftar dokumen proyek" });
}

describe("DocumentsPage", () => {
  describe("keadaan data", () => {
    it("memuat: skeleton tampil, tabel belum ada", async () => {
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      mockBackend();
      server.use(
        http.get(api("/projects/:id/documents"), async () => {
          await gate;
          return HttpResponse.json(successEnvelope(makeDocumentsData([makeDocument()])));
        })
      );
      renderPage("SA");
      expect(screen.getByRole("heading", { name: "Dokumen Proyek" })).toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByText(/Belum ada dokumen/)).not.toBeInTheDocument();
      release();
      await loaded();
    });

    it("kosong: pesan belum ada dokumen", async () => {
      mockBackend({ documents: [] });
      renderPage("SA");
      expect(await screen.findByText(/Belum ada dokumen/)).toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
    });

    it("error memuat daftar: alert gagal memuat", async () => {
      mockBackend();
      server.use(
        http.get(api("/projects/:id/documents"), () =>
          HttpResponse.json(errorEnvelope("boom"), { status: 500 })
        )
      );
      renderPage("SA");
      expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar dokumen. Silakan coba lagi.");
    });

    it("sukses: menampilkan tipe, status, catatan, dan header proyek", async () => {
      mockBackend({ documents: [makeDocument({ doc_type: "BOQ", status: "Reviewed", notes: "catatan BOQ" })] });
      renderPage("SA");
      await loaded();
      const row = screen.getByRole("row", { name: /BOQ/ });
      expect(within(row).getByText("Reviewed")).toBeInTheDocument();
      expect(within(row).getByText("catatan BOQ")).toBeInTheDocument();
      expect(await screen.findByText("Proyek Alfa — PT Beta")).toBeInTheDocument();
    });

    it("catatan kosong ditampilkan sebagai tanda strip", async () => {
      mockBackend({ documents: [makeDocument({ notes: null })] });
      renderPage("SA");
      await loaded();
      const cells = within(screen.getByRole("row", { name: /BOQ/ })).getAllByRole("cell");
      expect(cells[3]).toHaveTextContent("—");
    });

    it("gagal memuat proyek: dokumen tetap tampil tanpa header proyek", async () => {
      mockBackend({ project: null, documents: [makeDocument()] });
      renderPage("SA");
      await loaded();
      expect(screen.queryByText(/PT Beta/)).not.toBeInTheDocument();
      expect(screen.queryByText("Menunggu DQ")).not.toBeInTheDocument();
    });

    it("badge Menunggu DQ hanya saat dq_number null", async () => {
      mockBackend({
        documents: [makeDocument()],
        project: { id_project: PID, project_name: "A", customer_name: "B", status: "Intake", dq_number: null },
      });
      renderPage("SA");
      expect(await screen.findByText("Menunggu DQ")).toBeInTheDocument();
    });

    it("tanpa badge Menunggu DQ bila DQ sudah ada", async () => {
      mockBackend({ documents: [makeDocument()] });
      renderPage("SA");
      await screen.findByText("Proyek Alfa — PT Beta");
      expect(screen.queryByText("Menunggu DQ")).not.toBeInTheDocument();
    });
  });

  describe("link Drive", () => {
    it("dokumen dengan link: tautan Buka di Drive ke tab baru", async () => {
      mockBackend({ documents: [makeDocument({ gdrive_link: "https://drive.google.com/file/d/abc" })] });
      renderPage("SA");
      await loaded();
      const link = screen.getByRole("link", { name: "Buka dokumen BOQ di Google Drive" });
      expect(link).toHaveAttribute("href", "https://drive.google.com/file/d/abc");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveTextContent("Buka di Drive");
    });

    it("dokumen tanpa link (Requirement): tidak ada Buka di Drive, kolom berupa strip", async () => {
      mockBackend({ documents: [makeRequirementDoc({ gdrive_link: null })] });
      renderPage("Sales");
      await loaded();
      expect(screen.queryByText("Buka di Drive")).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Google Drive/ })).not.toBeInTheDocument();
      const row = screen.getAllByRole("row").find((r) => within(r).queryByText("Requirement"))!;
      expect(within(row).getAllByRole("cell")[2]).toHaveTextContent("—");
    });
  });

  describe("ubah status dokumen", () => {
    it("Draft → Reviewed: mengirim PATCH, memuat ulang, toast sukses hilang setelah 3 detik", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const be = mockBackend({ documents: [makeDocument({ status: "Draft" })] });
      setParams({ id: PID });
      seedAuth("SA");
      render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <DocumentsPage />
        </SWRConfig>
      );
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await loaded();
      await user.click(screen.getByRole("button", { name: "Ubah status BOQ ke Reviewed" }));

      expect(await screen.findByText("Status berhasil diubah ke Reviewed")).toBeInTheDocument();
      expect(be.requests).toEqual([`PATCH status ${be.documents[0].id_doc} Reviewed`]);
      expect(within(screen.getByRole("table")).getByText("Reviewed")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ubah status BOQ ke Final" })).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });
      expect(screen.queryByText("Status berhasil diubah ke Reviewed")).not.toBeInTheDocument();
    });

    it("gagal ubah status: toast error dengan pesan backend, tahan 5 detik", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      mockBackend({ documents: [makeDocument({ status: "Draft" })] });
      server.use(
        http.patch(api("/documents/:docId/status"), () =>
          HttpResponse.json(errorEnvelope("Transisi tidak valid"), { status: 400 })
        )
      );
      setParams({ id: PID });
      seedAuth("SA");
      render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <DocumentsPage />
        </SWRConfig>
      );
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      await loaded();
      await user.click(screen.getByRole("button", { name: "Ubah status BOQ ke Reviewed" }));
      expect(await screen.findByText("Transisi tidak valid")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });
      expect(screen.getByText("Transisi tidak valid")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(screen.queryByText("Transisi tidak valid")).not.toBeInTheDocument();
    });

    it("selama proses: tombol baris itu menampilkan Mengubah... dan nonaktif", async () => {
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      mockBackend({ documents: [makeDocument({ status: "Draft" })] });
      server.use(
        http.patch(api("/documents/:docId/status"), async () => {
          await gate;
          return HttpResponse.json(successEnvelope(makeDocument()));
        })
      );
      const { user } = renderPage("SA");
      await loaded();
      await user.click(screen.getByRole("button", { name: "Ubah status BOQ ke Reviewed" }));
      // aria-label tetap, teks berganti
      const busy = await screen.findByRole("button", { name: "Ubah status BOQ ke Reviewed" });
      await waitFor(() => expect(busy).toBeDisabled());
      expect(busy).toHaveTextContent("Mengubah...");
      release();
      await waitFor(() => expect(busy).not.toHaveTextContent("Mengubah..."));
    });
  });

  // Hak tulis dokumen per hubungan (#154): unggah/tambah = TULIS, majukan status = KELOLA,
  // edit butir Requirement = KELOLA_REQUIREMENT. Daftar dokumen tetap terbaca semua.
  describe("hak tulis per hubungan", () => {
    const KASUS: { role: Role; hubungan: Hubungan; tulis: boolean; kelola: boolean }[] = [
      { role: "SA", hubungan: "sa_utama", tulis: true, kelola: true },
      { role: "SA", hubungan: "sa_tambahan", tulis: true, kelola: true },
      { role: "SA", hubungan: "contributor", tulis: true, kelola: false },
      { role: "Lead_SA", hubungan: "tak_terkait", tulis: true, kelola: true },
      { role: "Admin", hubungan: "tak_terkait", tulis: true, kelola: true },
      { role: "Sales", hubungan: "sales_pic", tulis: false, kelola: false },
      { role: "Product", hubungan: "product_pic", tulis: false, kelola: false },
      { role: "SA", hubungan: "viewer", tulis: false, kelola: false },
      { role: "SA", hubungan: "tak_terkait", tulis: false, kelola: false },
      { role: "Sales", hubungan: "tak_terkait", tulis: false, kelola: false },
    ];

    it.each(KASUS)("$role sebagai $hubungan: Tambah Dokumen=$tulis, ubah status dan edit butir=$kelola", async ({ role, hubungan, tulis, kelola }) => {
      const project = pasangHubungan(role, hubungan, { id_project: PID, project_name: "Proyek Alfa", customer_name: "PT Beta", dq_number: "DQ-1" });
      mockBackend({ documents: [makeDocument({ status: "Draft" }), makeRequirementDoc()], project });
      renderPage(role);
      await loaded();
      // Konten baca tetap tampil untuk semua.
      expect(screen.getByText("Deploy di Kubernetes")).toBeInTheDocument();

      const tambah = () => screen.queryByRole("button", { name: "Tambah dokumen baru" });
      const ubahStatus = () => screen.queryByRole("button", { name: "Ubah status BOQ ke Reviewed" });
      const editButir = () => screen.queryByRole("button", { name: "+ Tambah butir" });
      if (tulis) expect(await screen.findByRole("button", { name: "Tambah dokumen baru" })).toBeInTheDocument();
      if (kelola) {
        expect(await screen.findByRole("button", { name: "Ubah status BOQ ke Reviewed" })).toBeInTheDocument();
        expect(await screen.findByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
      }
      if (!tulis || !kelola) await new Promise((r) => setTimeout(r, 50)); // beri waktu hubungan dimuat
      if (!tulis) expect(tambah()).not.toBeInTheDocument();
      if (!kelola) {
        expect(ubahStatus()).not.toBeInTheDocument();
        expect(editButir()).not.toBeInTheDocument();
      }
    });
  });

  describe("dokumen Final per peran", () => {
    const finalDoc = () => [makeDocument({ status: "Final" })];

    it.each<Role>(["SA", "Sales", "Product"])("%s: tidak bisa mengubah dokumen Final, ada keterangan Hanya Lead SA", async (role) => {
      mockBackend({ documents: finalDoc() });
      renderPage(role);
      await loaded();
      expect(screen.getByText("Hanya Lead SA")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Ubah status/ })).not.toBeInTheDocument();
    });

    it.each<Role>(["Lead_SA", "Admin"])("%s: dokumen Final tanpa transisi lanjutan (strip)", async (role) => {
      mockBackend({ documents: finalDoc() });
      renderPage(role);
      await loaded();
      expect(screen.queryByText("Hanya Lead SA")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Ubah status/ })).not.toBeInTheDocument();
    });
  });

  describe("tambah dokumen", () => {
    it("modal: isi form valid, POST, daftar dimuat ulang, modal tutup, toast sukses", async () => {
      const be = mockBackend({ documents: [] });
      const { user } = renderPage("SA");
      await screen.findByText(/Belum ada dokumen/);

      await user.click(screen.getByRole("button", { name: "Tambah dokumen baru" }));
      const dialog = screen.getByRole("dialog", { name: "Form tambah dokumen baru" });
      await user.selectOptions(within(dialog).getByLabelText(/Tipe Dokumen/), "MoM");
      await user.selectOptions(within(dialog).getByLabelText(/Folder Tujuan/), "Inventory");
      await user.type(within(dialog).getByLabelText(/Link Google Drive/), "https://drive.google.com/mom");
      await user.click(within(dialog).getByRole("button", { name: "Simpan Dokumen" }));

      expect(await screen.findByText("Dokumen berhasil ditambahkan")).toBeInTheDocument();
      expect(be.requests).toEqual([
        `POST documents ${JSON.stringify({
          doc_type: "MoM",
          gdrive_link: "https://drive.google.com/mom",
          folder_type: "Inventory",
        })}`,
      ]);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(await screen.findByRole("table")).toBeInTheDocument();
    });

    it("form di modal tidak menawarkan tipe Requirement", async () => {
      mockBackend();
      const { user } = renderPage("SA");
      await user.click(await screen.findByRole("button", { name: "Tambah dokumen baru" }));
      expect(screen.queryByRole("option", { name: "Requirement" })).not.toBeInTheDocument();
    });

    it("gagal membuat: toast error, modal tetap terbuka", async () => {
      mockBackend();
      server.use(
        http.post(api("/projects/:id/documents"), () =>
          HttpResponse.json(errorEnvelope("Link tidak valid"), { status: 422 })
        )
      );
      const { user } = renderPage("SA");
      await user.click(await screen.findByRole("button", { name: "Tambah dokumen baru" }));
      await user.selectOptions(screen.getByLabelText(/Tipe Dokumen/), "BOQ");
      await user.selectOptions(screen.getByLabelText(/Folder Tujuan/), "Solutions");
      await user.type(screen.getByLabelText(/Link Google Drive/), "https://x.y");
      await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));
      expect(await screen.findByText("Link tidak valid")).toBeInTheDocument();
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("modal bisa ditutup lewat Batal, tombol Tutup, dan klik latar; klik isi modal tidak menutup", async () => {
      mockBackend();
      const { user } = renderPage("SA");
      const open = () => user.click(screen.getByRole("button", { name: "Tambah dokumen baru" }));
      await screen.findByText(/Belum ada dokumen/);

      await open();
      await user.click(screen.getByRole("button", { name: "Batal" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      await open();
      await user.click(screen.getByRole("button", { name: "Tutup form" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      await open();
      await user.click(screen.getByRole("heading", { name: "Tambah Dokumen Baru" }));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      await user.click(screen.getByRole("dialog"));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("RAG panel", () => {
    it("proyek tanpa tags: pesan scoring belum selesai", async () => {
      mockBackend({ documents: [makeDocument()] });
      renderPage("SA");
      expect(await screen.findByText("Rekomendasi akan tersedia setelah scoring selesai")).toBeInTheDocument();
    });

    it("proyek dengan tags: memuat rekomendasi dari API", async () => {
      mockBackend({
        documents: [makeDocument()],
        project: {
          id_project: PID,
          project_name: "A",
          customer_name: "B",
          status: "Intake",
          dq_number: "DQ-1",
          use_case_tags: ["Cloud"],
        },
      });
      server.use(
        http.get(api("/projects/:id/recommendations"), () =>
          HttpResponse.json(
            successEnvelope([
              {
                id_project: "p9",
                project_name: "Referensi Lama",
                doc_type: "HLD",
                use_case_tags: ["Cloud"],
                gdrive_link: "https://drive.google.com/ref",
                match_count: 1,
              },
            ])
          )
        )
      );
      renderPage("SA");
      expect(await screen.findByRole("link", { name: /Referensi Lama/ })).toBeInTheDocument();
    });
  });

  describe("Requirement per peran", () => {
    const withRequirement = (over: Partial<Document> = {}, be: Partial<Backend> = {}) =>
      mockBackend({ documents: [makeRequirementDoc(over)], ...be });

    it("Sales: hanya melihat butir (read-only), tanpa banner meski sumber berubah", async () => {
      withRequirement({ source_changed: true, source_truncated: true });
      renderPage("Sales");
      await loaded();
      expect(screen.getByLabelText("Butir Requirement")).toBeInTheDocument();
      expect(screen.getByText("Deploy di Kubernetes")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("terpotong");
      expect(screen.queryByRole("button", { name: /Ubah butir/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "+ Tambah butir" })).not.toBeInTheDocument();
      expect(screen.queryByText(/Sumber Requirement/)).not.toBeInTheDocument();
    });

    it("SA yang ditugaskan: editor butir + banner bila sumber berubah", async () => {
      withRequirement({ source_changed: true });
      renderPage("SA");
      await loaded();
      expect(await screen.findByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" })).toBeInTheDocument();
      expect(screen.getByText(/Sumber Requirement/)).toBeInTheDocument();
    });

    it("SA yang tidak ditugaskan: read-only dan tanpa banner", async () => {
      withRequirement(
        { source_changed: true },
        {
          project: {
            id_project: PID,
            project_name: "A",
            customer_name: "B",
            status: "Intake",
            dq_number: "DQ-1",
            assigned_sa: { id: "orang-lain" },
          },
        }
      );
      renderPage("SA");
      await loaded();
      await screen.findByText("A — B");
      expect(screen.queryByRole("button", { name: "+ Tambah butir" })).not.toBeInTheDocument();
      expect(screen.queryByText(/Sumber Requirement/)).not.toBeInTheDocument();
    });

    it("SA tanpa penugasan (assigned_sa null): read-only", async () => {
      withRequirement(
        {},
        { project: { id_project: PID, project_name: "A", customer_name: "B", status: "Intake", dq_number: "DQ-1", assigned_sa: null } }
      );
      renderPage("SA");
      await loaded();
      await screen.findByText("A — B");
      expect(screen.queryByRole("button", { name: "+ Tambah butir" })).not.toBeInTheDocument();
    });

    it.each<Role>(["Lead_SA", "Admin"])("%s: editor butir tersedia tanpa perlu penugasan", async (role) => {
      withRequirement({}, { project: { id_project: PID, project_name: "A", customer_name: "B", status: "Intake", dq_number: "DQ-1" } });
      renderPage(role);
      await loaded();
      expect(await screen.findByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
    });

    it.each<Role>(["SA", "Lead_SA", "Admin"])("%s: dokumen Requirement Final menjadi read-only", async (role) => {
      withRequirement({ status: "Final" });
      renderPage(role);
      await loaded();
      await screen.findByText("Proyek Alfa — PT Beta");
      expect(screen.getByText("Deploy di Kubernetes")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Ubah butir/ })).not.toBeInTheDocument();
    });

    it("banner tidak tampil bila source_changed tidak ada", async () => {
      withRequirement({ source_changed: false });
      renderPage("Lead_SA");
      await loaded();
      await screen.findByRole("button", { name: "+ Tambah butir" });
      expect(screen.queryByText(/Sumber Requirement/)).not.toBeInTheDocument();
    });

    it("tambah butir lewat editor: POST, daftar dimuat ulang dan butir baru tampil", async () => {
      const be = withRequirement({});
      server.use(
        http.post(api("/projects/:id/requirement/items"), async ({ request }) => {
          const body = (await request.json()) as { kategori: "Asumsi"; butir: string };
          be.documents = [
            makeRequirementDoc({
              is_overridden: true,
              content: [...(be.documents[0].content ?? []), { id: "i-new", ...body }],
            }),
          ];
          return HttpResponse.json(successEnvelope(be.documents[0]), { status: 201 });
        })
      );
      const { user } = renderPage("Lead_SA");
      await user.click(await screen.findByRole("button", { name: "+ Tambah butir" }));
      await user.selectOptions(screen.getByLabelText("Kategori"), "Asumsi");
      await user.type(screen.getByLabelText("Butir"), "Akses VPN tersedia");
      await user.click(screen.getByRole("button", { name: "Simpan" }));

      expect(await screen.findByText("Akses VPN tersedia")).toBeInTheDocument();
      expect(screen.getByText("Sudah diedit manual.")).toBeInTheDocument();
    });

    it("gagal menyimpan butir: toast error halaman", async () => {
      withRequirement({});
      server.use(
        http.delete(api("/projects/:id/requirement/items/:itemId"), () =>
          HttpResponse.json(errorEnvelope("Tidak boleh menghapus"), { status: 403 })
        )
      );
      const { user } = renderPage("Admin");
      await user.click(await screen.findByRole("button", { name: "Hapus butir: Ekspor laporan PDF" }));
      expect(await screen.findByText("Tidak boleh menghapus")).toBeInTheDocument();
    });
  });

  describe("banner sumber berubah: hasil kedua aksi", () => {
    it("Pertahankan versi saya: banner hilang dan daftar di-refetch", async () => {
      const be = mockBackend({ documents: [makeRequirementDoc({ source_changed: true })] });
      server.use(
        http.post(api("/projects/:id/requirement/keep-version"), () => {
          be.documents = [makeRequirementDoc({ source_changed: false })];
          return HttpResponse.json(successEnvelope(null));
        })
      );
      const { user } = renderPage("Lead_SA");
      await user.click(await screen.findByRole("button", { name: "Pertahankan versi saya" }));

      await waitFor(() => expect(screen.queryByText(/Sumber Requirement/)).not.toBeInTheDocument());
      expect(be.listHits).toBeGreaterThan(1);
      // Konten tidak berubah
      expect(screen.getByText("Deploy di Kubernetes")).toBeInTheDocument();
    });

    it("Generate ulang: banner hilang, status berubah ke pending, section menampilkan sedang dibuat", async () => {
      const be = mockBackend({ documents: [makeRequirementDoc({ source_changed: true })], status: "ready", canRegenerate: true });
      server.use(
        http.post(api("/projects/:id/requirement/regenerate"), () => {
          be.documents = [makeRequirementDoc({ source_changed: false, is_overridden: false })];
          be.status = "pending";
          return HttpResponse.json(successEnvelope(null), { status: 202 });
        })
      );
      const { user } = renderPage("Lead_SA");
      await user.click(await screen.findByRole("button", { name: "Generate ulang (timpa edit saya)" }));

      await waitFor(() => expect(screen.queryByText(/Sumber Requirement/)).not.toBeInTheDocument());
      expect(await screen.findByText(/Requirement sedang dibuat/)).toBeInTheDocument();
    });

    it("aksi gagal: banner tetap ada dengan pesan error", async () => {
      mockBackend({ documents: [makeRequirementDoc({ source_changed: true })] });
      server.use(
        http.post(api("/projects/:id/requirement/keep-version"), () =>
          HttpResponse.json({ detail: "Tidak berhak" }, { status: 403 })
        )
      );
      const { user } = renderPage("Lead_SA");
      await user.click(await screen.findByRole("button", { name: "Pertahankan versi saya" }));
      expect(await screen.findByText("Tidak berhak")).toBeInTheDocument();
      expect(screen.getByText(/Sumber Requirement/)).toBeInTheDocument();
    });
  });

  describe("status generate Requirement di halaman", () => {
    it("failed + peran berhak: Coba lagi tampil di halaman", async () => {
      mockBackend({ documents: [makeRequirementDoc()], status: "failed", canRegenerate: true });
      renderPage("Admin");
      expect(await screen.findByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
    });

    it("pending → ready: daftar dokumen dimuat ulang otomatis lewat polling (fake timers)", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const be = mockBackend({ documents: [], status: "pending" });
      setParams({ id: PID });
      seedAuth("Lead_SA");
      render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <DocumentsPage />
        </SWRConfig>
      );
      expect(await screen.findByText(/Requirement sedang dibuat/)).toBeInTheDocument();
      expect(await screen.findByText(/Belum ada dokumen/)).toBeInTheDocument();

      be.documents = [makeRequirementDoc()];
      be.status = "ready";
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3200);
      });
      expect(await screen.findByText("Deploy di Kubernetes")).toBeInTheDocument();
      expect(screen.queryByText(/Belum ada dokumen/)).not.toBeInTheDocument();
    });
  });
});
