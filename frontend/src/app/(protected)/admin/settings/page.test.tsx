import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, router, seedAuth, server, successEnvelope } from "@/test";
import { ToastContainer } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";
import { makeAdminUsers } from "@/test/fixtures/shell";
import AdminSettingsPage from "./page";

const SETTINGS_KEY = "portal-sa-admin-settings";
const CATEGORIES_KEY = "portal-sa-categories";

function renderAdmin() {
  return renderWithProviders(
    <>
      <AdminSettingsPage />
      <ToastContainer />
    </>,
    { role: "Admin" },
  );
}

const sectionOf = (title: string) => screen.getByRole("heading", { name: title }).closest("div.rounded-lg") as HTMLElement;

afterEach(() => vi.useRealTimers());

describe("Pengaturan Admin — hak akses", () => {
  it.each(["Sales", "SA", "Lead_SA"] as const)("%s dialihkan ke '/' dan halaman tidak dirender", (role) => {
    const { container } = renderWithProviders(<AdminSettingsPage />, { role });
    expect(router.push).toHaveBeenCalledWith("/");
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("heading", { name: "Settings" })).not.toBeInTheDocument();
  });

  it("Admin melihat halaman dan tidak dialihkan", () => {
    renderAdmin();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("pengguna yang beralih dari non-Admin ke belum-login (logout) tidak membuat halaman crash", () => {
    seedAuth("SA");
    const { rerender } = renderWithProviders(<AdminSettingsPage />);
    expect(router.push).toHaveBeenCalledWith("/");
    expect(() => {
      act(() => useAuthStore.getState().clearUser());
      rerender(<AdminSettingsPage />);
    }).not.toThrow();
  });
});

describe("Pengaturan Admin — seksi kredensial", () => {
  it("menampilkan lima seksi; hanya LLM Provider terbuka sejak awal; accordion bisa dibuka/ditutup", async () => {
    const { user } = renderAdmin();
    for (const judul of ["Google OAuth 2.0", "Google Drive API", "Google Calendar API", "Gmail API", "LLM Provider"]) {
      expect(screen.getByRole("heading", { name: judul })).toBeInTheDocument();
    }
    const llm = screen.getByRole("button", { name: /LLM Provider/ });
    const oauth = screen.getByRole("button", { name: /Google OAuth 2.0/ });
    expect(llm).toHaveAttribute("aria-expanded", "true");
    expect(oauth).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Client ID")).not.toBeInTheDocument();

    await user.click(oauth);
    expect(oauth).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Client ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Allowed Domains")).toBeInTheDocument();

    await user.click(oauth);
    expect(screen.queryByLabelText("Client ID")).not.toBeInTheDocument();
  });

  it("memuat nilai tersimpan dari localStorage; JSON rusak jatuh ke nilai kosong", () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ LLM_MODEL_NAME: "model-x", LLM_PROVIDER: "openai" }));
    const { unmount } = renderAdmin();
    expect(screen.getByLabelText("Model Name")).toHaveValue("model-x");
    expect(screen.getByLabelText("Provider")).toHaveValue("openai");
    unmount();

    localStorage.setItem(SETTINGS_KEY, "{bukan json");
    renderAdmin();
    expect(screen.getByLabelText("Model Name")).toHaveValue("");
    expect(screen.getByLabelText("Provider")).toHaveValue("gemini");
  });

  it("field password tersembunyi secara default dan bisa ditampilkan/disembunyikan", async () => {
    const { user } = renderAdmin();
    const key = screen.getByLabelText("Gemini API Key");
    expect(key).toHaveAttribute("type", "password");
    const toggles = screen.getAllByRole("button", { name: "Tampilkan" });
    await user.click(toggles[0]);
    expect(key).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Sembunyikan" }));
    expect(key).toHaveAttribute("type", "password");
  });

  it("textarea (JSON) dan teks dapat diisi pada seksi yang dibuka", async () => {
    const { user } = renderAdmin();
    await user.click(screen.getByRole("button", { name: /Gmail API/ }));
    const area = screen.getByLabelText("Credentials (JSON)");
    await user.click(area);
    await user.paste('{"a":1}');
    expect(area).toHaveValue('{"a":1}');
  });

  it("Simpan: tombol 'Menyimpan...' selama 500 ms, lalu tersimpan ke localStorage dan toast sukses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = renderAdmin();
    await user.type(screen.getByLabelText("Model Name"), "gemini-pro");
    const llm = sectionOf("LLM Provider");
    await user.click(within(llm).getByRole("button", { name: "Simpan" }));

    expect(within(llm).getByRole("button", { name: "Menyimpan..." })).toBeDisabled();
    expect(localStorage.getItem(SETTINGS_KEY)).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(JSON.parse(localStorage.getItem(SETTINGS_KEY)!)).toMatchObject({ LLM_MODEL_NAME: "gemini-pro" });
    expect(within(llm).getByRole("button", { name: "Simpan" })).toBeEnabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Settings berhasil disimpan. Restart container untuk menerapkan perubahan.");
  });

  it("Test Koneksi tanpa API key: toast error menyebut provider", async () => {
    const { user } = renderAdmin();
    await user.click(screen.getByRole("button", { name: "Test Koneksi" }));
    expect(screen.getByRole("alert")).toHaveTextContent("API Key untuk gemini belum diisi.");
  });

  it.each([
    ["gemini", "Gemini API Key"],
    ["openai", "OpenAI API Key"],
    ["anthropic", "Anthropic API Key"],
  ])("Test Koneksi %s memakai key yang sesuai: info lalu sukses setelah 1,5 detik", async (provider, label) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = renderAdmin();
    await user.selectOptions(screen.getByLabelText("Provider"), provider);
    await user.type(screen.getByLabelText(label), "kunci-rahasia");
    await user.click(screen.getByRole("button", { name: "Test Koneksi" }));

    expect(screen.getByRole("alert")).toHaveTextContent(`Testing koneksi ke ${provider}...`);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(screen.getByText(`Koneksi ke ${provider} berhasil! ✓`)).toBeInTheDocument();
  });

  it("Test Koneksi hanya ada pada seksi LLM", async () => {
    renderAdmin();
    expect(screen.getAllByRole("button", { name: "Test Koneksi" })).toHaveLength(1);
  });
});

describe("Pengaturan Admin — kategori aktivitas", () => {
  const cat = () => sectionOf("Kategori Aktivitas");

  it("menampilkan kategori bawaan saat belum ada data tersimpan", () => {
    renderAdmin();
    expect(within(cat()).getByText("Meeting Pre-Sales")).toBeInTheDocument();
    expect(within(cat()).getAllByRole("button", { name: "Hapus" })).toHaveLength(6);
  });

  it("memuat kategori tersimpan; JSON rusak jatuh ke bawaan", () => {
    localStorage.setItem(CATEGORIES_KEY, JSON.stringify(["Khusus"]));
    const { unmount } = renderAdmin();
    expect(within(cat()).getByText("Khusus")).toBeInTheDocument();
    expect(within(cat()).queryByText("Meeting Pre-Sales")).not.toBeInTheDocument();
    unmount();

    localStorage.setItem(CATEGORIES_KEY, "###");
    renderAdmin();
    expect(within(cat()).getByText("Meeting Pre-Sales")).toBeInTheDocument();
  });

  it("menambah kategori: tersimpan, input dikosongkan, toast sukses; Enter juga menambah", async () => {
    const { user } = renderAdmin();
    const input = within(cat()).getByPlaceholderText("Nama kategori baru...");
    const tambah = within(cat()).getByRole("button", { name: "Tambah" });
    expect(tambah).toBeDisabled();

    await user.type(input, "  Demo Produk  ");
    await user.click(tambah);
    expect(within(cat()).getByText("Demo Produk")).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(JSON.parse(localStorage.getItem(CATEGORIES_KEY)!)).toContain("Demo Produk");
    expect(screen.getByRole("alert")).toHaveTextContent('Kategori "Demo Produk" ditambahkan.');

    await user.type(input, "Lewat Enter{Enter}");
    expect(within(cat()).getByText("Lewat Enter")).toBeInTheDocument();
  });

  it("menolak kategori duplikat dengan toast error dan tidak menambah", async () => {
    const { user } = renderAdmin();
    await user.type(within(cat()).getByPlaceholderText("Nama kategori baru..."), "Create BOQ");
    await user.click(within(cat()).getByRole("button", { name: "Tambah" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Kategori sudah ada.");
    expect(within(cat()).getAllByText("Create BOQ")).toHaveLength(1);
    expect(localStorage.getItem(CATEGORIES_KEY)).toBeNull();
  });

  it("Enter pada input kosong tidak menambah apa pun", async () => {
    const { user } = renderAdmin();
    await user.type(within(cat()).getByPlaceholderText("Nama kategori baru..."), "{Enter}");
    expect(within(cat()).getAllByRole("button", { name: "Hapus" })).toHaveLength(6);
  });

  it("menghapus kategori", async () => {
    const { user } = renderAdmin();
    await user.click(within(cat()).getAllByRole("button", { name: "Hapus" })[0]);
    expect(within(cat()).queryByText("Meeting Pre-Sales")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Kategori dihapus.");
    expect(JSON.parse(localStorage.getItem(CATEGORIES_KEY)!)).toHaveLength(5);
  });

  it("mengubah kategori (tombol Simpan dan Enter), membatalkan, dan mengabaikan nilai kosong", async () => {
    const { user } = renderAdmin();
    await user.click(within(cat()).getAllByRole("button", { name: "Edit" })[0]);
    const edit = within(cat()).getByDisplayValue("Meeting Pre-Sales");
    await user.clear(edit);
    await user.type(edit, "Rapat Awal");
    await user.click(within(cat()).getByRole("button", { name: "Simpan" }));
    expect(within(cat()).getByText("Rapat Awal")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Kategori diubah.");

    await user.click(within(cat()).getAllByRole("button", { name: "Edit" })[1]);
    const edit2 = within(cat()).getByDisplayValue("Create PropTek");
    await user.clear(edit2);
    await user.type(edit2, "PropTek Baru{Enter}");
    expect(within(cat()).getByText("PropTek Baru")).toBeInTheDocument();

    await user.click(within(cat()).getAllByRole("button", { name: "Edit" })[0]);
    const edit3 = within(cat()).getByDisplayValue("Rapat Awal");
    await user.clear(edit3);
    await user.click(within(cat()).getByRole("button", { name: "Simpan" })); // kosong → diabaikan
    expect(edit3).toHaveValue("");
    await user.click(within(cat()).getByRole("button", { name: "Batal" }));
    expect(within(cat()).getByText("Rapat Awal")).toBeInTheDocument();
  });
});

describe("Pengaturan Admin — user & role", () => {
  const um = () => sectionOf("User & Role Management");

  it("memuat: skeleton", () => {
    server.use(http.get(api("/admin/users"), () => new Promise(() => {})));
    renderAdmin();
    expect(um().querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("kosong: pesan belum ada user", async () => {
    server.use(http.get(api("/admin/users"), () => HttpResponse.json(successEnvelope([]))));
    renderAdmin();
    expect(await within(um()).findByText("Belum ada user terdaftar.")).toBeInTheDocument();
  });

  it("error: diperlakukan sebagai kosong (tidak ada UI error khusus)", async () => {
    server.use(http.get(api("/admin/users"), () => HttpResponse.json({ message: "x" }, { status: 500 })));
    renderAdmin();
    expect(await within(um()).findByText("Belum ada user terdaftar.")).toBeInTheDocument();
  });

  it("berisi: tabel user dengan peran dan aksi Ubah Role", async () => {
    server.use(
      http.get(api("/admin/users"), () =>
        HttpResponse.json(
          successEnvelope([
            ...makeAdminUsers(),
            { id: "u3", name: "Lead", email: "lead@example.com", role: "Lead_SA" },
            { id: "u4", name: "Esa", email: "esa@example.com", role: "SA" },
          ]),
        ),
      ),
    );
    renderAdmin();
    const table = await within(um()).findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByText("admin@example.com")).toBeInTheDocument();
    expect(within(table).getByText("Admin")).toHaveClass("bg-purple-100");
    expect(within(table).getByText("Lead_SA")).toHaveClass("bg-blue-100");
    expect(within(table).getByText("SA")).toHaveClass("bg-green-100");
    expect(within(table).getByText("Sales")).toHaveClass("bg-neutral-100");
    expect(within(table).getAllByRole("button", { name: "Ubah Role" })).toHaveLength(4);
  });

  it("ubah role: modal terisi role sekarang, PATCH terkirim, toast sukses, daftar dimuat ulang", async () => {
    let patched: unknown = null;
    let gets = 0;
    server.use(
      http.get(api("/admin/users"), () => {
        gets++;
        return HttpResponse.json(successEnvelope(makeAdminUsers()));
      }),
      http.patch(api("/admin/users/:id/role"), async ({ request, params }) => {
        patched = { id: params.id, body: await request.json() };
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = renderAdmin();
    await user.click((await within(um()).findAllByRole("button", { name: "Ubah Role" }))[0]);

    expect(screen.getByRole("heading", { name: "Ubah Role" })).toBeInTheDocument();
    expect(screen.getByText("Sales Demo (sales@example.com)")).toBeInTheDocument();
    const select = within(screen.getByRole("heading", { name: "Ubah Role" }).closest("div.fixed") as HTMLElement).getByRole("combobox");
    expect(select).toHaveValue("Sales");
    await user.selectOptions(select, "SA");
    const modal = screen.getByRole("heading", { name: "Ubah Role" }).closest("div.fixed") as HTMLElement;
    await user.click(within(modal).getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Role Sales Demo diubah ke SA."));
    expect(patched).toEqual({ id: "00000000-0000-4000-8000-000000000001", body: { role: "SA" } });
    expect(screen.queryByRole("heading", { name: "Ubah Role" })).not.toBeInTheDocument();
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
  });

  it("Batal menutup modal tanpa mengirim apa pun", async () => {
    let patched = 0;
    server.use(
      http.patch(api("/admin/users/:id/role"), () => {
        patched++;
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = renderAdmin();
    await user.click((await within(um()).findAllByRole("button", { name: "Ubah Role" }))[0]);
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("heading", { name: "Ubah Role" })).not.toBeInTheDocument();
    expect(patched).toBe(0);
  });

  it("penolakan backend (mis. Admin terakhir) menampilkan pesan server dan modal tetap terbuka", async () => {
    server.use(
      http.patch(api("/admin/users/:id/role"), () =>
        HttpResponse.json({ status: "error", data: null, message: "Admin terakhir tidak dapat di-demote" }, { status: 409 }),
      ),
    );
    const { user } = renderAdmin();
    const tombol = await within(um()).findAllByRole("button", { name: "Ubah Role" });
    await user.click(tombol[1]);
    const modal = screen.getByRole("heading", { name: "Ubah Role" }).closest("div.fixed") as HTMLElement;
    await user.selectOptions(within(modal).getByRole("combobox"), "Sales");
    await user.click(within(modal).getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Admin terakhir tidak dapat di-demote"));
    expect(screen.getByRole("heading", { name: "Ubah Role" })).toBeInTheDocument();
  });
});
