import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, gagalLaluBerhasil, http, pasangHubungan, renderWithProviders, server, successEnvelope, type Hubungan, type Role } from "@/test";
import { makeCollaborator, makeUserSearchResult } from "@/test/fixtures/operations";
import { CollaboratorSection } from "./CollaboratorSection";

const SEARCH_POOL = [
  makeUserSearchResult({ id: "u-sa", name: "Dani SA", email: "dani@example.com", role: "SA" }),
  makeUserSearchResult({ id: "u-sales", name: "Sari Sales", email: "sari@example.com", role: "Sales" }),
  makeUserSearchResult({ id: "u-lead", name: "Lina Lead", email: "lina@example.com", role: "Lead_SA" }),
];

function useSearchPool() {
  server.use(http.get(api("/projects/users/search"), () => HttpResponse.json(successEnvelope(SEARCH_POOL))));
}

// Hubungan bawaan: pengguna berhak (SA = SA utama, Sales/Product = PIC); privileged tak terkait.
const HUBUNGAN_BAWAAN: Record<Role, Hubungan> = {
  SA: "sa_utama",
  Sales: "sales_pic",
  Product: "product_pic",
  Lead_SA: "tak_terkait",
  Admin: "tak_terkait",
};

function setup(
  role: Role = "SA",
  props: Partial<React.ComponentProps<typeof CollaboratorSection>> = {},
  hubungan: Hubungan = HUBUNGAN_BAWAAN[role],
) {
  pasangHubungan(role, hubungan);
  const onMutate = vi.fn();
  const utils = renderWithProviders(<CollaboratorSection projectId="p-1" onMutate={onMutate} {...props} />, { role });
  return { onMutate, ...utils };
}

async function openFormAndSearch(user: ReturnType<typeof setup>["user"], q: string) {
  await user.click(screen.getByRole("button", { name: "+ Tambah" }));
  await user.type(screen.getByPlaceholderText("Ketik minimal 2 karakter..."), q);
}

describe("CollaboratorSection — daftar", () => {
  it("menampilkan kolaborator dari server dengan badge peran", async () => {
    server.use(
      http.get(api("/projects/:id/collaborators"), () =>
        HttpResponse.json(
          successEnvelope({
            items: [makeCollaborator(), makeCollaborator({ id: "c2", user_id: "u2", user_name: "Edo", user_email: "edo@x.com", role: "contributor" })],
            total: 2,
          })
        )
      )
    );
    setup();
    expect(await screen.findByText("Citra Dewi")).toBeInTheDocument();
    expect(screen.getByText("Viewer")).toBeInTheDocument();
    expect(screen.getByText("Contributor")).toBeInTheDocument();
    expect(screen.getByText("citra@example.com", { exact: false })).toBeInTheDocument();
  });

  it("memakai initialCollaborators sebelum data server tiba", async () => {
    setup("SA", { initialCollaborators: [makeCollaborator({ user_name: "Awal Dulu" }) as never] });
    expect(screen.getByText("Awal Dulu")).toBeInTheDocument();
    expect(await screen.findByText("Citra Dewi")).toBeInTheDocument();
    expect(screen.queryByText("Awal Dulu")).not.toBeInTheDocument();
  });

  it("keadaan kosong bila belum ada kolaborator", async () => {
    server.use(http.get(api("/projects/:id/collaborators"), () => HttpResponse.json(successEnvelope({ items: [], total: 0 }))));
    setup();
    expect(await screen.findByText("Belum ada kolaborator di proyek ini.")).toBeInTheDocument();
  });

  it("daftar gagal dimuat: pesan error (bukan 'Belum ada kolaborator'), coba lagi memuat ulang", async () => {
    server.use(gagalLaluBerhasil("/projects/:id/collaborators", { items: [makeCollaborator({ user_name: "Pulih Dewi" })], total: 1 }));
    const { user } = setup();

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar kolaborator.");
    expect(screen.queryByText("Belum ada kolaborator di proyek ini.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("Pulih Dewi")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("daftar gagal dimuat tetapi ada initialCollaborators: daftar awal tetap tampil bersama pesan error", async () => {
    server.use(http.get(api("/projects/:id/collaborators"), () => HttpResponse.json(errorEnvelope("gagal"), { status: 500 })));
    setup("SA", { initialCollaborators: [makeCollaborator({ user_name: "Awal Dulu" }) as never] });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar kolaborator.");
    expect(screen.getByText("Awal Dulu")).toBeInTheDocument();
  });

  it("pencarian user gagal: pesan error (bukan 'Tidak ada user yang cocok'), coba lagi memuat ulang hasil", async () => {
    server.use(gagalLaluBerhasil("/projects/users/search", SEARCH_POOL));
    const { user } = setup();
    await screen.findByText("Citra Dewi");
    await openFormAndSearch(user, "da");

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal mencari user.");
    expect(screen.queryByText(/Tidak ada user yang cocok/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("Dani SA")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("CollaboratorSection — hak akses per peran", () => {
  it.each<Role>(["SA", "Sales", "Product", "Lead_SA", "Admin"])("%s melihat tombol tambah dan hapus", async (role) => {
    setup(role);
    await screen.findByText("Citra Dewi");
    expect(screen.getByRole("button", { name: "+ Tambah" })).toBeInTheDocument();
    expect(screen.getByTitle("Hapus kolaborator")).toBeInTheDocument();
  });

  // Hak tambah/hapus kolaborator = TingkatAkses.TAMBAH_/HAPUS_KOLABORATOR (#154): SA ditugaskan
  // (utama/tambahan) dan Sales/Product PIC; contributor, viewer, dan pengguna tak terkait ditolak.
  const KASUS: { role: Role; hubungan: Hubungan; berhak: boolean }[] = [
    { role: "SA", hubungan: "sa_utama", berhak: true },
    { role: "SA", hubungan: "sa_tambahan", berhak: true },
    { role: "Sales", hubungan: "sales_pic", berhak: true },
    { role: "Product", hubungan: "product_pic", berhak: true },
    { role: "Lead_SA", hubungan: "tak_terkait", berhak: true },
    { role: "Admin", hubungan: "tak_terkait", berhak: true },
    { role: "SA", hubungan: "contributor", berhak: false },
    { role: "SA", hubungan: "viewer", berhak: false },
    { role: "Sales", hubungan: "contributor", berhak: false },
    { role: "SA", hubungan: "tak_terkait", berhak: false },
    { role: "Sales", hubungan: "tak_terkait", berhak: false },
    { role: "Product", hubungan: "tak_terkait", berhak: false },
    { role: "Sales", hubungan: "viewer", berhak: false },
  ];

  it.each(KASUS)("$role sebagai $hubungan: kontrol kelola tampil=$berhak, daftar tetap terbaca", async ({ role, hubungan, berhak }) => {
    setup(role, {}, hubungan);
    expect(await screen.findByText("Citra Dewi")).toBeInTheDocument();
    if (berhak) {
      expect(await screen.findByRole("button", { name: "+ Tambah" })).toBeInTheDocument();
      expect(screen.getByTitle("Hapus kolaborator")).toBeInTheDocument();
    } else {
      // Beri waktu hubungan (detail + tim SA) selesai dimuat sebelum menyimpulkan "tersembunyi".
      await waitFor(() => expect(screen.getByText("Citra Dewi")).toBeInTheDocument());
      await new Promise((r) => setTimeout(r, 50));
      expect(screen.queryByRole("button", { name: "+ Tambah" })).not.toBeInTheDocument();
      expect(screen.queryByTitle("Hapus kolaborator")).not.toBeInTheDocument();
    }
  });

  it("pengguna tanpa peran (belum login) tidak bisa mengelola", async () => {
    renderWithProviders(<CollaboratorSection projectId="p-1" />);
    await screen.findByText("Citra Dewi");
    expect(screen.queryByRole("button", { name: "+ Tambah" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Hapus kolaborator")).not.toBeInTheDocument();
  });

  it("SA: keterangan batasan dan hanya kandidat SA yang muncul", async () => {
    useSearchPool();
    const { user } = setup("SA");
    await openFormAndSearch(user, "da");
    expect(screen.getByText("Sebagai SA, Anda hanya dapat menambahkan sesama SA.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Dani SA/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sari Sales/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Lina Lead/ })).not.toBeInTheDocument();
  });

  it.each<Role>(["Sales", "Product"])("%s: keterangan batasan dan hanya kandidat Sales/Product yang muncul", async (role) => {
    useSearchPool();
    const { user } = setup(role);
    await openFormAndSearch(user, "sa");
    expect(screen.getByText("Sebagai Sales/Product, Anda hanya dapat menambahkan sesama Sales/Product.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Sari Sales/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dani SA/ })).not.toBeInTheDocument();
  });

  it.each<Role>(["Lead_SA", "Admin"])("%s: tanpa keterangan batasan dan semua kandidat muncul", async (role) => {
    useSearchPool();
    const { user } = setup(role);
    await openFormAndSearch(user, "da");
    expect(screen.queryByText(/hanya dapat menambahkan sesama/)).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Dani SA/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sari Sales/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lina Lead/ })).toBeInTheDocument();
  });
});

describe("CollaboratorSection — tambah kolaborator", () => {
  it("tombol toggle berganti Batal / + Tambah dan menutup form", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "+ Tambah" }));
    expect(screen.getByText("Cari user (nama atau email):")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByText("Cari user (nama atau email):")).not.toBeInTheDocument();
  });

  it("tombol 'Tambah Kolaborator' nonaktif sebelum ada user terpilih", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "+ Tambah" }));
    expect(screen.getByRole("button", { name: "Tambah Kolaborator" })).toBeDisabled();
  });

  it("tidak mengirim request pencarian untuk query < 2 karakter", async () => {
    const search = vi.fn();
    server.use(http.get(api("/projects/users/search"), () => { search(); return HttpResponse.json(successEnvelope([])); }));
    const { user } = setup();
    await openFormAndSearch(user, "d");
    expect(search).not.toHaveBeenCalled();
    expect(screen.queryByText(/Tidak ada user yang cocok/)).not.toBeInTheDocument();
  });

  it("mengirim query ter-encode dan limit ke endpoint pencarian", async () => {
    let url: URL | undefined;
    server.use(http.get(api("/projects/users/search"), ({ request }) => { url = new URL(request.url); return HttpResponse.json(successEnvelope([])); }));
    const { user } = setup();
    await openFormAndSearch(user, "a&b");
    await waitFor(() => expect(url).toBeDefined());
    expect(url!.searchParams.get("q")).toBe("a&b");
    expect(url!.searchParams.get("limit")).toBe("10");
  });

  it("pesan tidak ada kandidat tampil bila hasil kosong setelah filter peran", async () => {
    server.use(http.get(api("/projects/users/search"), () => HttpResponse.json(successEnvelope([SEARCH_POOL[1]]))));
    const { user } = setup("SA"); // hanya Sales dikembalikan -> terfilter habis
    await openFormAndSearch(user, "sa");
    expect(await screen.findByText("Tidak ada user yang cocok dan diizinkan untuk ditambahkan.")).toBeInTheDocument();
  });

  it("memilih user menampilkan kartu terpilih dan tombol ✕ membatalkan pilihan", async () => {
    useSearchPool();
    const { user } = setup("Lead_SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    expect(screen.getByText("dani@example.com — SA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tambah Kolaborator" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "✕" }));
    expect(screen.queryByText("dani@example.com — SA")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ketik minimal 2 karakter...")).toHaveValue("");
  });

  it("mengubah teks pencarian setelah memilih membatalkan pilihan", async () => {
    useSearchPool();
    const { user } = setup("Lead_SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    await user.type(screen.getByPlaceholderText("Ketik minimal 2 karakter..."), "x");
    expect(screen.queryByText("dani@example.com — SA")).not.toBeInTheDocument();
  });

  it("klik di luar area pencarian membatalkan pilihan user", async () => {
    useSearchPool();
    const { user } = setup("Lead_SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    expect(screen.getByText("dani@example.com — SA")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByText("dani@example.com — SA")).not.toBeInTheDocument());
  });

  it("klik di dalam area pencarian tidak membatalkan pilihan", async () => {
    useSearchPool();
    const { user } = setup("Lead_SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    fireEvent.mouseDown(screen.getByPlaceholderText("Ketik minimal 2 karakter..."));
    expect(screen.getByText("dani@example.com — SA")).toBeInTheDocument();
  });

  it("regresi: mousedown pada kontrol lain di dalam form (peran, tombol tambah) tidak membatalkan pilihan user", async () => {
    useSearchPool();
    const { user } = setup("SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    fireEvent.mouseDown(screen.getByRole("button", { name: /Contributor — Bisa tambah/ }));
    fireEvent.mouseDown(screen.getByRole("button", { name: "Tambah Kolaborator" }));
    expect(screen.getByText("dani@example.com — SA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tambah Kolaborator" })).toBeEnabled();
  });

  it("user Sales yang dipilih tidak boleh jadi contributor: tombol dinonaktifkan dan peran kembali viewer", async () => {
    useSearchPool();
    const { user } = setup("Lead_SA");
    await openFormAndSearch(user, "sa");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    const contributor = screen.getByRole("button", { name: /Contributor — Bisa tambah Activity Log/ });
    await user.click(contributor);
    // pilih ulang user Sales
    await user.clear(screen.getByPlaceholderText("Ketik minimal 2 karakter..."));
    await user.type(screen.getByPlaceholderText("Ketik minimal 2 karakter..."), "sa");
    await user.click(await screen.findByRole("button", { name: /Sari Sales/ }));
    const disabled = screen.getByRole("button", { name: /Contributor — Bisa tambah Activity Log/ });
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveAttribute("title", "Hanya SA yang bisa menjadi contributor");
  });

  it("sukses: mengirim user_id + peran terpilih, menutup form, dan memanggil onMutate", async () => {
    useSearchPool();
    let body: unknown;
    let refetched = 0;
    server.use(
      http.post(api("/projects/:id/collaborators"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope({}), { status: 201 });
      }),
      http.get(api("/projects/:id/collaborators"), () => {
        refetched++;
        return HttpResponse.json(successEnvelope({ items: [], total: 0 }));
      })
    );
    const { user, onMutate } = setup("SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    await user.click(screen.getByRole("button", { name: /Contributor — Bisa tambah Activity Log/ }));
    const before = refetched;
    await user.click(screen.getByRole("button", { name: "Tambah Kolaborator" }));

    await waitFor(() => expect(onMutate).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ user_id: "u-sa", role: "contributor" });
    expect(screen.queryByText("Cari user (nama atau email):")).not.toBeInTheDocument();
    await waitFor(() => expect(refetched).toBeGreaterThan(before)); // daftar divalidasi ulang
  });

  it("memilih peran Viewer kembali setelah Contributor", async () => {
    useSearchPool();
    let body: unknown;
    server.use(http.post(api("/projects/:id/collaborators"), async ({ request }) => { body = await request.json(); return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup("SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    await user.click(screen.getByRole("button", { name: /Contributor — Bisa tambah/ }));
    await user.click(screen.getByRole("button", { name: /Viewer — Bisa melihat proyek/ }));
    await user.click(screen.getByRole("button", { name: "Tambah Kolaborator" }));
    await waitFor(() => expect(body).toEqual({ user_id: "u-sa", role: "viewer" }));
  });

  it("menampilkan 'Menambahkan...' selama request", async () => {
    useSearchPool();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/projects/:id/collaborators"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user, onMutate } = setup("SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    await user.click(screen.getByRole("button", { name: "Tambah Kolaborator" }));
    expect(await screen.findByRole("button", { name: "Menambahkan..." })).toBeDisabled();
    release();
    await waitFor(() => expect(onMutate).toHaveBeenCalled());
  });

  it("error server saat menambah ditampilkan dan form tetap terbuka", async () => {
    useSearchPool();
    server.use(http.post(api("/projects/:id/collaborators"), () => HttpResponse.json(errorEnvelope("User sudah menjadi kolaborator"), { status: 409 })));
    const { user, onMutate } = setup("SA");
    await openFormAndSearch(user, "da");
    await user.click(await screen.findByRole("button", { name: /Dani SA/ }));
    await user.click(screen.getByRole("button", { name: "Tambah Kolaborator" }));
    expect(await screen.findByText("User sudah menjadi kolaborator")).toBeInTheDocument();
    expect(screen.getByText("Cari user (nama atau email):")).toBeInTheDocument();
    expect(onMutate).not.toHaveBeenCalled();
  });
});

describe("CollaboratorSection — hapus kolaborator", () => {
  it("konfirmasi disetujui: DELETE ke endpoint user lalu onMutate", async () => {
    let path = "";
    server.use(http.delete(api("/projects/:id/collaborators/:userId"), ({ request }) => { path = new URL(request.url).pathname; return HttpResponse.json(successEnvelope(null)); }));
    const { user, onMutate } = setup("SA");
    await screen.findByText("Citra Dewi");
    await user.click(screen.getByTitle("Hapus kolaborator"));
    expect(window.confirm).toHaveBeenCalledWith("Hapus Citra Dewi dari kolaborator proyek ini?");
    await waitFor(() => expect(onMutate).toHaveBeenCalledTimes(1));
    expect(path).toBe("/api/v1/projects/p-1/collaborators/u-collab-1");
  });

  it("konfirmasi ditolak: tidak ada request dan tidak ada onMutate", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const del = vi.fn();
    server.use(http.delete(api("/projects/:id/collaborators/:userId"), () => { del(); return HttpResponse.json(successEnvelope(null)); }));
    const { user, onMutate } = setup("SA");
    await screen.findByText("Citra Dewi");
    await user.click(screen.getByTitle("Hapus kolaborator"));
    expect(del).not.toHaveBeenCalled();
    expect(onMutate).not.toHaveBeenCalled();
  });

  it("error server saat menghapus ditampilkan", async () => {
    server.use(http.delete(api("/projects/:id/collaborators/:userId"), () => HttpResponse.json(errorEnvelope("Tidak berhak menghapus"), { status: 403 })));
    const { user, onMutate } = setup("SA");
    const row = (await screen.findByText("Citra Dewi")).closest("div.flex")!.parentElement as HTMLElement;
    await user.click(within(row).getByTitle("Hapus kolaborator"));
    expect(await screen.findByText("Tidak berhak menghapus")).toBeInTheDocument();
    expect(onMutate).not.toHaveBeenCalled();
  });
});
