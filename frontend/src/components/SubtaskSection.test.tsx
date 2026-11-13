import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { users } from "@/test/fixtures/users";
import { makeSATambahan, makeSubtask, makeTimSA } from "@/test/fixtures/project-detail";
import { SubtaskSection } from "./SubtaskSection";

const SA_ID = users.SA.id;

const semua = [
  makeSubtask({ id_subtask: "a", title: "Milik SA", status: "open", assigned_sa: SA_ID, assigned_sa_name: "SA Demo" }),
  makeSubtask({ id_subtask: "b", title: "Milik SA lain", status: "done", assigned_sa: "lain", assigned_sa_name: "SA Lain" }),
  makeSubtask({ id_subtask: "c", title: "Tak ditugaskan", status: "in_progress" }),
  makeSubtask({ id_subtask: "d", title: "Sudah selesai milik SA", status: "done", assigned_sa: SA_ID, assigned_sa_name: "SA Demo" }),
];

function serve(items = semua) {
  server.use(http.get(api("/projects/p1/subtasks"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))));
}

function setup(role?: Role) {
  return renderWithProviders(<SubtaskSection projectId="p1" />, role ? { role } : {});
}

describe("SubtaskSection — visibilitas per peran", () => {
  it.each(["Sales", "Product"] as const)("%s tidak melihat section apa pun", (role) => {
    serve();
    const { container } = setup(role);
    expect(container).toBeEmptyDOMElement();
  });

  it("tanpa user (belum login) tidak merender apa pun", () => {
    serve();
    const { container } = setup();
    expect(container).toBeEmptyDOMElement();
  });

  it("SA hanya melihat subtask miliknya, tanpa kontrol tambah/tugaskan/hapus", async () => {
    serve();
    setup("SA");
    expect(await screen.findByText("Milik SA")).toBeInTheDocument();
    expect(screen.getByText("Sudah selesai milik SA")).toBeInTheDocument();
    expect(screen.queryByText("Milik SA lain")).not.toBeInTheDocument();
    expect(screen.queryByText("Tak ditugaskan")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Tambah" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tugaskan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hapus subtask/ })).not.toBeInTheDocument();
    expect(screen.getByText("Work item yang ditugaskan kepada Anda.")).toBeInTheDocument();
  });

  it("SA: ringkasan N/M dihitung dari seluruh subtask proyek, bukan hanya miliknya", async () => {
    serve();
    setup("SA");
    expect(await screen.findByText("2/4 selesai")).toBeInTheDocument();
    expect(screen.getByLabelText("2 dari 4 subtask selesai")).toBeInTheDocument();
  });

  it("SA: tombol 'Tandai selesai' hanya untuk subtask milik yang belum selesai", async () => {
    serve();
    setup("SA");
    await screen.findByText("Milik SA");
    expect(screen.getAllByRole("button", { name: "Tandai selesai" })).toHaveLength(1);
  });

  it("SA tidak memicu fetch tim SA untuk kontrol assign", async () => {
    serve();
    let dipanggil = false;
    server.use(http.get(api("/projects/p1/tim-sa"), () => { dipanggil = true; return HttpResponse.json(successEnvelope(makeTimSA())); }));
    setup("SA");
    await screen.findByText("Milik SA");
    expect(dipanggil).toBe(false);
  });

  it.each(["Lead_SA", "Admin"] as const)("%s melihat seluruh subtask dan kontrol kelola", async (role) => {
    serve();
    setup(role);
    for (const t of ["Milik SA", "Milik SA lain", "Tak ditugaskan", "Sudah selesai milik SA"]) {
      expect(await screen.findByText(t)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "+ Tambah" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Tugaskan" })).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: /Hapus subtask/ })).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Tandai selesai" })).not.toBeInTheDocument();
    expect(screen.getByText("Work item teknis proyek — tambah, tugaskan, atau hapus.")).toBeInTheDocument();
  });

  it("Lead_SA melihat badge status dan 'Belum ditugaskan'", async () => {
    serve();
    setup("Lead_SA");
    await screen.findByText("Tak ditugaskan");
    expect(screen.getByText("Terbuka")).toBeInTheDocument();
    expect(screen.getByText("Dikerjakan")).toBeInTheDocument();
    expect(screen.getAllByText("Selesai")).toHaveLength(2);
    expect(screen.getByText("Belum ditugaskan")).toBeInTheDocument();
  });
});

describe("SubtaskSection — keadaan data", () => {
  it("menampilkan skeleton saat memuat lalu daftar", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api("/projects/p1/subtasks"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope({ items: [semua[0]], total: 1 }));
      }),
    );
    const { container } = setup("SA");
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    expect(screen.queryByText(/Belum ada subtask/)).not.toBeInTheDocument();
    lepas();
    expect(await screen.findByText("Milik SA")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).not.toBeInTheDocument();
  });

  it("keadaan kosong untuk Lead_SA", async () => {
    serve([]);
    setup("Lead_SA");
    expect(await screen.findByText("Belum ada subtask di proyek ini.")).toBeInTheDocument();
    expect(screen.queryByText(/selesai$/)).not.toBeInTheDocument();
  });

  it("keadaan kosong untuk SA", async () => {
    serve([semua[1]]);
    setup("SA");
    expect(await screen.findByText("Belum ada subtask yang ditugaskan kepada Anda.")).toBeInTheDocument();
  });

  it.each<Role>(["Lead_SA", "SA"])("%s: error memuat tampil sebagai pesan error (bukan keadaan kosong) dan bisa dicoba ulang", async (role) => {
    server.use(gagalLaluBerhasil("/projects/p1/subtasks", { items: semua, total: semua.length }));
    const { user } = setup(role);

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar subtask.");
    expect(screen.queryByText("Belum ada subtask di proyek ini.")).not.toBeInTheDocument();
    expect(screen.queryByText("Belum ada subtask yang ditugaskan kepada Anda.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("Milik SA")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("SubtaskSection — Lead_SA/Admin menambah", () => {
  it("form tambah: buka/tutup, tombol nonaktif bila judul kosong", async () => {
    serve([]);
    const { user } = setup("Lead_SA");
    await screen.findByText("Belum ada subtask di proyek ini.");
    const toggle = screen.getByRole("button", { name: "+ Tambah" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Batal" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Tambah Subtask" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByLabelText("Judul subtask:")).not.toBeInTheDocument();
  });

  it("menambah via tombol: kirim judul ter-trim, form menutup, daftar dimuat ulang", async () => {
    let items: typeof semua = [];
    let body: unknown;
    server.use(
      http.get(api("/projects/p1/subtasks"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))),
      http.post(api("/projects/p1/subtasks"), async ({ request }) => {
        body = await request.json();
        items = [makeSubtask({ id_subtask: "baru", title: "Peer Review HLD" })];
        return HttpResponse.json(successEnvelope(items[0]), { status: 201 });
      }),
    );
    const { user } = setup("Lead_SA");
    await screen.findByText("Belum ada subtask di proyek ini.");
    await user.click(screen.getByRole("button", { name: "+ Tambah" }));
    await user.type(screen.getByLabelText("Judul subtask:"), "  Peer Review HLD  ");
    await user.click(screen.getByRole("button", { name: "Tambah Subtask" }));
    expect(await screen.findByText("Peer Review HLD")).toBeInTheDocument();
    expect(body).toEqual({ title: "Peer Review HLD" });
    expect(screen.queryByLabelText("Judul subtask:")).not.toBeInTheDocument();
  });

  it("menambah via Enter; Enter pada judul kosong tidak mengirim", async () => {
    serve([]);
    let jumlah = 0;
    server.use(http.post(api("/projects/p1/subtasks"), () => { jumlah++; return HttpResponse.json(successEnvelope(makeSubtask()), { status: 201 }); }));
    const { user } = setup("Admin");
    await screen.findByText("Belum ada subtask di proyek ini.");
    await user.click(screen.getByRole("button", { name: "+ Tambah" }));
    await user.type(screen.getByLabelText("Judul subtask:"), "{Enter}");
    expect(jumlah).toBe(0);
    await user.type(screen.getByLabelText("Judul subtask:"), "Judul{Enter}");
    await waitFor(() => expect(jumlah).toBe(1));
  });

  it("gagal menambah: tampil pesan server di alert, form tetap terbuka", async () => {
    serve([]);
    server.use(http.post(api("/projects/p1/subtasks"), () => HttpResponse.json(errorEnvelope("Judul duplikat"), { status: 409 })));
    const { user } = setup("Lead_SA");
    await screen.findByText("Belum ada subtask di proyek ini.");
    await user.click(screen.getByRole("button", { name: "+ Tambah" }));
    await user.type(screen.getByLabelText("Judul subtask:"), "X");
    await user.click(screen.getByRole("button", { name: "Tambah Subtask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Judul duplikat");
    expect(screen.getByLabelText("Judul subtask:")).toHaveValue("X");
    // membuka/menutup form menghapus error
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("SubtaskSection — hapus", () => {
  it("konfirmasi disetujui: DELETE dikirim dan daftar dimuat ulang", async () => {
    let items = [semua[0], semua[2]];
    let dihapus = "";
    server.use(
      http.get(api("/projects/p1/subtasks"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))),
      http.delete(api("/projects/subtasks/:id"), ({ params }) => {
        dihapus = String(params.id);
        items = items.filter((i) => i.id_subtask !== params.id);
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("Lead_SA");
    await screen.findByText("Milik SA");
    await user.click(screen.getByRole("button", { name: "Hapus subtask Milik SA" }));
    expect(window.confirm).toHaveBeenCalledWith('Hapus subtask "Milik SA"?');
    await waitFor(() => expect(screen.queryByText("Milik SA")).not.toBeInTheDocument());
    expect(dihapus).toBe("a");
  });

  it("konfirmasi ditolak: tidak ada request", async () => {
    serve();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    let dipanggil = false;
    server.use(http.delete(api("/projects/subtasks/:id"), () => { dipanggil = true; return HttpResponse.json(successEnvelope(null)); }));
    const { user } = setup("Lead_SA");
    await screen.findByText("Milik SA");
    await user.click(screen.getByRole("button", { name: "Hapus subtask Milik SA" }));
    expect(dipanggil).toBe(false);
    expect(screen.getByText("Milik SA")).toBeInTheDocument();
  });

  it("gagal hapus: pesan server ditampilkan", async () => {
    serve();
    server.use(http.delete(api("/projects/subtasks/:id"), () => HttpResponse.json(errorEnvelope("Tidak boleh dihapus"), { status: 403 })));
    const { user } = setup("Lead_SA");
    await screen.findByText("Milik SA");
    await user.click(screen.getByRole("button", { name: "Hapus subtask Milik SA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tidak boleh dihapus");
  });
});

describe("SubtaskSection — tandai selesai (SA)", () => {
  it("mengirim PATCH status done lalu memuat ulang daftar", async () => {
    let items = [semua[0]];
    let body: unknown;
    server.use(
      http.get(api("/projects/p1/subtasks"), () => HttpResponse.json(successEnvelope({ items, total: items.length }))),
      http.patch(api("/projects/subtasks/a/status"), async ({ request }) => {
        body = await request.json();
        items = [{ ...items[0], status: "done" }];
        return HttpResponse.json(successEnvelope(items[0]));
      }),
    );
    const { user } = setup("SA");
    await user.click(await screen.findByRole("button", { name: "Tandai selesai" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Tandai selesai" })).not.toBeInTheDocument());
    expect(body).toEqual({ status: "done" });
    expect(screen.getByText("Selesai")).toBeInTheDocument();
    expect(screen.getByText("1/1 selesai")).toBeInTheDocument();
  });

  it("saat menyimpan tombol menjadi 'Menyimpan...' dan nonaktif", async () => {
    serve([semua[0]]);
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.patch(api("/projects/subtasks/a/status"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("SA");
    await user.click(await screen.findByRole("button", { name: "Tandai selesai" }));
    expect(await screen.findByRole("button", { name: "Menyimpan..." })).toBeDisabled();
    lepas();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Menyimpan..." })).not.toBeInTheDocument());
  });

  it("gagal: pesan server ditampilkan", async () => {
    serve([semua[0]]);
    server.use(http.patch(api("/projects/subtasks/a/status"), () => HttpResponse.json(errorEnvelope("Transisi tidak valid"), { status: 422 })));
    const { user } = setup("SA");
    await user.click(await screen.findByRole("button", { name: "Tandai selesai" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Transisi tidak valid");
  });
});

describe("SubtaskSection — tugaskan (Lead_SA/Admin)", () => {
  // Assignee subtask harus anggota tim SA project (ADR 0014): opsi datang dari tim SA, bukan
  // dari seluruh SA di sistem.
  const tim = makeTimSA({
    sa_utama: { id: "sa-1", name: "Andi", email: "a@x" },
    sa_tambahan: [makeSATambahan({ id: "sa-2", name: "Budi", email: "b@x" })],
  });
  const timHandler = () => http.get(api("/projects/p1/tim-sa"), () => HttpResponse.json(successEnvelope(tim)));

  it("panel dibuka/ditutup, daftar SA memuat jumlah proyek, memilih SA mengirim PATCH", async () => {
    serve([makeSubtask({ id_subtask: "t1", title: "Tugas 1" })]);
    let body: unknown;
    server.use(
      timHandler(),
      http.patch(api("/projects/subtasks/t1/assign"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("Lead_SA");
    await screen.findByText("Tugas 1");
    const tugaskan = screen.getByRole("button", { name: "Tugaskan" });
    await user.click(tugaskan);
    expect(tugaskan).toHaveAttribute("aria-expanded", "true");
    const select = await screen.findByLabelText("Tugaskan ke SA:");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Andi (SA utama)" })).toBeInTheDocument());
    expect(within(select).getByRole("option", { name: "Budi (SA tambahan)" })).toBeInTheDocument();
    await user.selectOptions(select, "sa-2");
    await waitFor(() => expect(body).toEqual({ assigned_sa: "sa-2" }));
    await waitFor(() => expect(screen.queryByLabelText("Tugaskan ke SA:")).not.toBeInTheDocument());
  });

  it("klik Tugaskan dua kali menutup panel", async () => {
    serve([makeSubtask({ id_subtask: "t1", title: "Tugas 1" })]);
    const { user } = setup("Admin");
    await screen.findByText("Tugas 1");
    await user.click(screen.getByRole("button", { name: "Tugaskan" }));
    expect(screen.getByLabelText("Tugaskan ke SA:")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tugaskan" }));
    expect(screen.queryByLabelText("Tugaskan ke SA:")).not.toBeInTheDocument();
  });

  it("memilih 'Lepas penugasan' mengirim assigned_sa null", async () => {
    serve([makeSubtask({ id_subtask: "t1", title: "Tugas 1", assigned_sa: "sa-1", assigned_sa_name: "Andi" })]);
    let body: unknown;
    server.use(
      timHandler(),
      http.patch(api("/projects/subtasks/t1/assign"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const { user } = setup("Lead_SA");
    await screen.findByText("Tugas 1");
    await user.click(screen.getByRole("button", { name: "Tugaskan" }));
    const select = await screen.findByLabelText("Tugaskan ke SA:");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    await user.selectOptions(select, "");
    await waitFor(() => expect(body).toEqual({ assigned_sa: null }));
  });

  it("gagal menugaskan: pesan server ditampilkan, panel tetap terbuka", async () => {
    serve([makeSubtask({ id_subtask: "t1", title: "Tugas 1" })]);
    server.use(
      timHandler(),
      http.patch(api("/projects/subtasks/t1/assign"), () => HttpResponse.json(errorEnvelope("SA penuh"), { status: 409 })),
    );
    const { user } = setup("Lead_SA");
    await screen.findByText("Tugas 1");
    await user.click(screen.getByRole("button", { name: "Tugaskan" }));
    const select = await screen.findByLabelText("Tugaskan ke SA:");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    await user.selectOptions(select, "sa-1");
    expect(await screen.findByRole("alert")).toHaveTextContent("SA penuh");
    expect(screen.getByLabelText("Tugaskan ke SA:")).toBeInTheDocument();
  });
});
