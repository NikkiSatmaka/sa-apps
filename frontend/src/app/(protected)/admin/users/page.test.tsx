import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, api, gagalLaluBerhasil, renderWithProviders, router, seedAuth, server, successEnvelope } from "@/test";
import { ToastContainer } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";
import { makeAdminUsers } from "@/test/fixtures/shell";
import AdminUsersPage from "./page";

function renderAdmin() {
  return renderWithProviders(
    <>
      <AdminUsersPage />
      <ToastContainer />
    </>,
    { role: "Admin" },
  );
}

const sectionOf = (title: string) => screen.getByRole("heading", { name: title }).closest("div.rounded-lg") as HTMLElement;

afterEach(() => vi.useRealTimers());

describe("Manajemen Pengguna Admin — hak akses", () => {
  it.each(["Sales", "Product", "SA", "Lead_SA"] as const)("%s (bukan admin) dialihkan ke '/' dan halaman tidak dirender", (role) => {
    const { container } = renderWithProviders(<AdminUsersPage />, { role });
    expect(router.push).toHaveBeenCalledWith("/");
    expect(container).toBeEmptyDOMElement();
  });

  it("Lead_SA dengan is_admin melihat halaman (hak berbasis flag, bukan role)", () => {
    seedAuth("Lead_SA", { is_admin: true });
    renderWithProviders(<AdminUsersPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Pengguna" })).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("Admin melihat halaman dan tidak dialihkan", () => {
    renderAdmin();
    expect(screen.getByRole("heading", { level: 1, name: "Pengguna" })).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("pengguna yang beralih dari non-Admin ke belum-login (logout) tidak membuat halaman crash", () => {
    seedAuth("SA");
    const { rerender } = renderWithProviders(<AdminUsersPage />);
    expect(router.push).toHaveBeenCalledWith("/");
    expect(() => {
      act(() => useAuthStore.getState().clearUser());
      rerender(<AdminUsersPage />);
    }).not.toThrow();
  });

  it("tidak menulis kunci localStorage pengaturan/kategori (tanpa kredensial di browser)", async () => {
    renderAdmin();
    await screen.findByRole("table");
    const keys = Object.keys(localStorage).filter((k) => /settings|categories|portal-sa/i.test(k));
    expect(keys).toEqual([]);
  });
});

describe("Manajemen Pengguna Admin", () => {
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

  it("error: pesan error (bukan 'Belum ada user terdaftar'), coba lagi memuat ulang tabel", async () => {
    server.use(gagalLaluBerhasil("/admin/users", makeAdminUsers()));
    const { user } = renderAdmin();

    expect(await within(um()).findByRole("alert")).toHaveTextContent("Gagal memuat daftar user.");
    expect(within(um()).queryByText("Belum ada user terdaftar.")).not.toBeInTheDocument();

    await user.click(within(um()).getByRole("button", { name: "Coba lagi" }));

    expect(await within(um()).findByRole("table")).toBeInTheDocument();
    expect(within(um()).queryByRole("alert")).not.toBeInTheDocument();
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
    const baris = (email: string) => within(table).getByText(email).closest("tr") as HTMLElement;
    expect(within(table).getAllByRole("row")).toHaveLength(6); // header + 5 user
    // Role fungsional dan flag admin tampil terpisah; admin menempel pada role (ADR 0012).
    expect(within(baris("admin@example.com")).getByText("SA")).toHaveClass("bg-green-100");
    expect(within(baris("admin@example.com")).getByText("Admin")).toHaveClass("bg-purple-100");
    expect(within(baris("lead@example.com")).getByText("Lead_SA")).toHaveClass("bg-blue-100");
    expect(within(baris("lead@example.com")).queryByText("Admin")).not.toBeInTheDocument();
    expect(within(baris("sales@example.com")).getByText("Sales")).toHaveClass("bg-neutral-100");
    expect(within(baris("product@example.com")).getByText("Product")).toHaveClass("bg-neutral-100");
    expect(within(table).getAllByRole("button", { name: "Ubah Role" })).toHaveLength(5);
    // Aksi flag: cabut untuk admin, jadikan admin untuk yang lain
    expect(within(baris("admin@example.com")).getByRole("button", { name: "Cabut Admin" })).toBeInTheDocument();
    expect(within(baris("lead@example.com")).getByRole("button", { name: "Jadikan Admin" })).toBeInTheDocument();
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
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Sales",
      "Product",
      "SA",
      "Lead_SA",
    ]);
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

  it("penolakan backend menampilkan pesan server dan modal tetap terbuka", async () => {
    server.use(
      http.patch(api("/admin/users/:id/role"), () =>
        HttpResponse.json({ status: "error", data: null, message: "Role tidak valid" }, { status: 400 }),
      ),
    );
    const { user } = renderAdmin();
    const tombol = await within(um()).findAllByRole("button", { name: "Ubah Role" });
    await user.click(tombol[2]);
    const modal = screen.getByRole("heading", { name: "Ubah Role" }).closest("div.fixed") as HTMLElement;
    await user.selectOptions(within(modal).getByRole("combobox"), "Sales");
    await user.click(within(modal).getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Role tidak valid"));
    expect(screen.getByRole("heading", { name: "Ubah Role" })).toBeInTheDocument();
  });
});

describe("Manajemen Pengguna Admin — flag admin", () => {
  const um = () => sectionOf("User & Role Management");
  const barisDari = async (email: string) => {
    const table = await within(um()).findByRole("table");
    return within(table).getByText(email).closest("tr") as HTMLElement;
  };

  it("Jadikan Admin: PATCH /admin/users/:id/admin {is_admin:true}, toast sukses, daftar dimuat ulang", async () => {
    let patched: unknown = null;
    let gets = 0;
    server.use(
      http.get(api("/admin/users"), () => {
        gets++;
        return HttpResponse.json(successEnvelope(makeAdminUsers()));
      }),
      http.patch(api("/admin/users/:id/admin"), async ({ request, params }) => {
        patched = { id: params.id, body: await request.json() };
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = renderAdmin();

    await user.click(within(await barisDari("sales@example.com")).getByRole("button", { name: "Jadikan Admin" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Sales Demo dijadikan admin."));
    expect(patched).toEqual({ id: "00000000-0000-4000-8000-000000000001", body: { is_admin: true } });
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
  });

  it("Cabut Admin: PATCH {is_admin:false} dan toast sukses", async () => {
    let body: unknown = null;
    server.use(
      http.patch(api("/admin/users/:id/admin"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = renderAdmin();

    await user.click(within(await barisDari("admin@example.com")).getByRole("button", { name: "Cabut Admin" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Flag admin Admin Demo dicabut."));
    expect(body).toEqual({ is_admin: false });
  });

  it("penolakan backend (admin terakhir) menampilkan pesan server", async () => {
    server.use(
      http.patch(api("/admin/users/:id/admin"), () =>
        HttpResponse.json(
          { status: "error", data: null, message: "Admin terakhir tidak dapat dicabut." },
          { status: 409 },
        ),
      ),
    );
    const { user } = renderAdmin();

    await user.click(within(await barisDari("admin@example.com")).getByRole("button", { name: "Cabut Admin" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Admin terakhir tidak dapat dicabut."));
  });
});
