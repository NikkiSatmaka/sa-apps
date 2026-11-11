import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import { makeRequirementDoc } from "@/test/fixtures/requirement";
import { RequirementItemsEditor } from "./RequirementItemsEditor";

const PID = "proj-1";

/** Rekam permintaan butir ke MSW (method, path, body). */
function recordItemRequests() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const record = async ({ request }: { request: Request }) => {
    const text = await request.text();
    calls.push({
      method: request.method,
      path: new URL(request.url).pathname,
      body: text ? JSON.parse(text) : null,
    });
    return HttpResponse.json(successEnvelope(makeRequirementDoc({ is_overridden: true })));
  };
  server.use(
    http.post(api("/projects/:id/requirement/items"), record),
    http.put(api("/projects/:id/requirement/items/:itemId"), record),
    http.delete(api("/projects/:id/requirement/items/:itemId"), record)
  );
  return calls;
}

function setup(props: Partial<React.ComponentProps<typeof RequirementItemsEditor>> = {}) {
  const onChanged = vi.fn();
  const onError = vi.fn();
  const doc = props.doc ?? makeRequirementDoc();
  const utils = renderWithProviders(
    <RequirementItemsEditor projectId={PID} doc={doc} onChanged={onChanged} onError={onError} {...props} />
  );
  return { ...utils, onChanged, onError };
}

describe("RequirementItemsEditor", () => {
  it("menampilkan butir per kategori dengan tombol Ubah dan Hapus per butir", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Fungsional" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Teknis" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hapus butir: Deploy di Kubernetes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
  });

  it("keadaan kosong: pesan belum ada butir, tetap bisa menambah", () => {
    setup({ doc: makeRequirementDoc({ content: null }) });
    expect(screen.getByText("Belum ada butir.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
  });

  it("menampilkan peringatan terpotong dan penanda sudah diedit manual sesuai dokumen", () => {
    const { unmount } = setup({ doc: makeRequirementDoc({ source_truncated: true, is_overridden: true }) });
    expect(screen.getByRole("status")).toHaveTextContent("terpotong");
    expect(screen.getByText("Sudah diedit manual.")).toBeInTheDocument();
    unmount();
    setup();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("Sudah diedit manual.")).not.toBeInTheDocument();
  });

  describe("tambah", () => {
    it("mengirim POST dengan kategori & butir ter-trim, lalu memanggil onChanged dan menutup form", async () => {
      const calls = recordItemRequests();
      const { user, onChanged, onError } = setup();

      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));
      // Form tambah: tombol tambah disembunyikan, kategori default Fungsional
      expect(screen.queryByRole("button", { name: "+ Tambah butir" })).not.toBeInTheDocument();
      expect(screen.getByLabelText("Kategori")).toHaveValue("Fungsional");

      await user.selectOptions(screen.getByLabelText("Kategori"), "Kepatuhan");
      await user.type(screen.getByLabelText("Butir"), "  Patuh ISO 27001  ");
      await user.click(screen.getByRole("button", { name: "Simpan" }));

      await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
      expect(calls).toEqual([
        {
          method: "POST",
          path: "/api/v1/projects/proj-1/requirement/items",
          body: { kategori: "Kepatuhan", butir: "Patuh ISO 27001" },
        },
      ]);
      expect(onError).not.toHaveBeenCalled();
      expect(screen.queryByLabelText("Butir")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "+ Tambah butir" })).toBeInTheDocument();
    });

    it("kategori yang ditawarkan adalah enam kategori tetap", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));
      const options = Array.from((screen.getByLabelText("Kategori") as HTMLSelectElement).options).map(
        (o) => o.value
      );
      expect(options).toEqual(["Fungsional", "Teknis", "Kepatuhan", "Integrasi", "Timeline", "Asumsi"]);
    });
  });

  describe("validasi", () => {
    it("Simpan nonaktif saat butir kosong atau hanya spasi, aktif saat ada isi; tidak ada request", async () => {
      const calls = recordItemRequests();
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));

      const simpan = screen.getByRole("button", { name: "Simpan" });
      expect(simpan).toBeDisabled();
      await user.type(screen.getByLabelText("Butir"), "   ");
      expect(simpan).toBeDisabled();
      await user.click(simpan);
      expect(calls).toHaveLength(0);

      await user.type(screen.getByLabelText("Butir"), "x");
      expect(simpan).toBeEnabled();
    });

    it("mengosongkan butir saat ubah menonaktifkan Simpan", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" }));
      const textarea = screen.getByLabelText("Butir");
      expect(textarea).toHaveValue("Deploy di Kubernetes");
      await user.clear(textarea);
      expect(screen.getByRole("button", { name: "Simpan" })).toBeDisabled();
    });

    it("textarea membatasi 1000 karakter", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));
      expect(screen.getByLabelText("Butir")).toHaveAttribute("maxlength", "1000");
    });
  });

  describe("ubah", () => {
    it("mengisi form dengan butir terpilih lalu mengirim PUT ke id butir tersebut", async () => {
      const calls = recordItemRequests();
      const { user, onChanged } = setup();

      await user.click(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" }));
      expect(screen.getByLabelText("Kategori")).toHaveValue("Teknis");
      expect(screen.getByLabelText("Butir")).toHaveValue("Deploy di Kubernetes");

      await user.selectOptions(screen.getByLabelText("Kategori"), "Integrasi");
      await user.clear(screen.getByLabelText("Butir"));
      await user.type(screen.getByLabelText("Butir"), "Integrasi dengan ERP");
      await user.click(screen.getByRole("button", { name: "Simpan" }));

      await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
      expect(calls).toEqual([
        {
          method: "PUT",
          path: "/api/v1/projects/proj-1/requirement/items/i-2",
          body: { kategori: "Integrasi", butir: "Integrasi dengan ERP" },
        },
      ]);
      expect(screen.queryByLabelText("Butir")).not.toBeInTheDocument();
    });

    it("Batal menutup form tanpa request", async () => {
      const calls = recordItemRequests();
      const { user, onChanged } = setup();
      await user.click(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" }));
      await user.click(screen.getByRole("button", { name: "Batal" }));
      expect(screen.queryByLabelText("Butir")).not.toBeInTheDocument();
      expect(calls).toHaveLength(0);
      expect(onChanged).not.toHaveBeenCalled();
    });
  });

  describe("hapus", () => {
    it("setelah konfirmasi mengirim DELETE ke id butir lalu onChanged", async () => {
      const calls = recordItemRequests();
      const { user, onChanged } = setup();
      await user.click(screen.getByRole("button", { name: "Hapus butir: Ekspor laporan PDF" }));

      expect(window.confirm).toHaveBeenCalledWith("Hapus butir ini?");
      await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
      expect(calls).toEqual([
        { method: "DELETE", path: "/api/v1/projects/proj-1/requirement/items/i-3", body: null },
      ]);
    });

    it("batal di dialog konfirmasi: tidak ada request", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const calls = recordItemRequests();
      const { user, onChanged } = setup();
      await user.click(screen.getByRole("button", { name: "Hapus butir: Ekspor laporan PDF" }));
      expect(calls).toHaveLength(0);
      expect(onChanged).not.toHaveBeenCalled();
    });
  });

  describe("error dan keadaan sibuk", () => {
    it("gagal simpan: onError menerima pesan backend, form tetap terbuka, onChanged tidak dipanggil", async () => {
      server.use(
        http.post(api("/projects/:id/requirement/items"), () =>
          HttpResponse.json(errorEnvelope("Butir terlalu panjang"), { status: 422 })
        )
      );
      const { user, onChanged, onError } = setup();
      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));
      await user.type(screen.getByLabelText("Butir"), "isi");
      await user.click(screen.getByRole("button", { name: "Simpan" }));

      await waitFor(() => expect(onError).toHaveBeenCalledWith("Butir terlalu panjang"));
      expect(onChanged).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Butir")).toHaveValue("isi");
      expect(screen.getByRole("button", { name: "Simpan" })).toBeEnabled();
    });

    it("gagal hapus: onError dipanggil dengan detail dari backend", async () => {
      server.use(
        http.delete(api("/projects/:id/requirement/items/:itemId"), () =>
          HttpResponse.json({ detail: "Dokumen sudah Final" }, { status: 403 })
        )
      );
      const { user, onError } = setup();
      await user.click(screen.getByRole("button", { name: "Hapus butir: Ekspor laporan PDF" }));
      await waitFor(() => expect(onError).toHaveBeenCalledWith("Dokumen sudah Final"));
    });

    it("kegagalan bukan Error: onError memakai pesan bawaan", async () => {
      const { user, onError } = setup({ onChanged: () => Promise.reject("boom") });
      await user.click(screen.getByRole("button", { name: "Hapus butir: Ekspor laporan PDF" }));
      await waitFor(() => expect(onError).toHaveBeenCalledWith("Gagal menyimpan butir Requirement"));
    });

    it("selama menyimpan: tombol menampilkan Menyimpan... dan semua aksi dinonaktifkan", async () => {
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      server.use(
        http.post(api("/projects/:id/requirement/items"), async () => {
          await gate;
          return HttpResponse.json(successEnvelope(makeRequirementDoc()));
        })
      );
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "+ Tambah butir" }));
      await user.type(screen.getByLabelText("Butir"), "baru");
      await user.click(screen.getByRole("button", { name: "Simpan" }));

      expect(await screen.findByRole("button", { name: "Menyimpan..." })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Ubah butir: Deploy di Kubernetes" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Hapus butir: Deploy di Kubernetes" })).toBeDisabled();
      release();
      await waitFor(() => expect(screen.queryByLabelText("Butir")).not.toBeInTheDocument());
    });
  });
});
