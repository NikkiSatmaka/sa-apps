import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, router, server, successEnvelope, type Role } from "@/test";
import { makeProject } from "@/test/fixtures/projects";
import ProjectsPage from "./page";

const proyek = [
  makeProject({ id_project: "id-aaa", project_name: "Alfa Cloud", customer_name: "PT Satu", status: "Assigned", dq_number: "DQ-1" }),
  makeProject({ id_project: "id-bbb", project_name: "Beta Security", customer_name: "PT Dua", status: "Intake", dq_number: null }),
  makeProject({ id_project: "id-ccc", project_name: "Gamma Data", customer_name: "Satu Sejahtera", status: "Lost", dq_number: null }),
];

/** Rekam URL request daftar proyek dan sajikan data. */
function serve(data = proyek) {
  const urls: URL[] = [];
  server.use(
    http.get(api("/projects"), ({ request }) => {
      urls.push(new URL(request.url));
      return HttpResponse.json(successEnvelope(data));
    }),
  );
  return urls;
}

function setup(role: Role) {
  return renderWithProviders(<ProjectsPage />, { role });
}

const SEMUA_PERAN = ["Sales", "Product", "SA", "Lead_SA", "Admin"] as const;

describe("Daftar proyek — daftar penuh untuk semua peran (#109, ADR 0011)", () => {
  it.each(SEMUA_PERAN)("%s: meminta daftar penuh tanpa penyempit, urut terbaru", async (role) => {
    const urls = serve();
    setup(role);
    await screen.findByText("Alfa Cloud");
    expect(urls[0].searchParams.has("involved")).toBe(false);
    expect(urls[0].searchParams.has("sales_pic")).toBe(false);
    expect(urls[0].searchParams.has("assigned_to")).toBe(false);
    expect(urls[0].searchParams.get("sort")).toBe("-updated_at");
    expect(screen.getByText("Semua proyek")).toBeInTheDocument();
  });

  it.each(SEMUA_PERAN)("%s: sakelar 'Hanya proyek saya' ada dan default mati", async (role) => {
    serve();
    setup(role);
    await screen.findByText("Alfa Cloud");
    expect(screen.getByRole("checkbox", { name: "Hanya proyek saya" })).not.toBeChecked();
  });

  it("sakelar proyek memakai checkbox 18px dengan label target 44px", async () => {
    serve();
    setup("SA");
    const checkbox = await screen.findByRole("checkbox", { name: "Hanya proyek saya" });

    expect(checkbox).toHaveClass("h-[18px]", "w-[18px]", "min-h-[18px]", "min-w-[18px]");
    expect(checkbox.closest("label")).toHaveClass("min-h-[44px]");
  });

  it.each(SEMUA_PERAN)("%s: sakelar menyempitkan lewat involved=me dan bisa dimatikan lagi", async (role) => {
    const urls: URL[] = [];
    server.use(
      http.get(api("/projects"), ({ request }) => {
        const url = new URL(request.url);
        urls.push(url);
        const sempit = url.searchParams.get("involved") === "me";
        return HttpResponse.json(successEnvelope(sempit ? [proyek[0]] : proyek));
      }),
    );
    const { user } = setup(role);
    await screen.findByText("Menampilkan 3 dari 3 proyek");

    await user.click(screen.getByRole("checkbox", { name: "Hanya proyek saya" }));
    expect(await screen.findByText("Menampilkan 1 dari 1 proyek")).toBeInTheDocument();
    expect(urls.at(-1)!.searchParams.get("involved")).toBe("me");
    expect(urls.at(-1)!.searchParams.get("sort")).toBe("-updated_at");
    expect(screen.queryByText("Beta Security")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Hanya proyek saya" }));
    expect(await screen.findByText("Menampilkan 3 dari 3 proyek")).toBeInTheDocument();
    await waitFor(() => expect(urls.at(-1)!.searchParams.has("involved")).toBe(false));
    expect(screen.getByRole("checkbox", { name: "Hanya proyek saya" })).not.toBeChecked();
  });

  it("tanpa user tidak memanggil API", async () => {
    const urls = serve();
    renderWithProviders(<ProjectsPage />);
    await new Promise((r) => setTimeout(r, 30));
    expect(urls).toHaveLength(0);
  });

  it("urutan kartu mengikuti urutan dari server", async () => {
    serve();
    setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    const judul = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(judul).toEqual(["Alfa Cloud", "Beta Security", "Gamma Data"]);
  });
});

describe("Daftar proyek — tombol Request SA per peran", () => {
  it.each(["Sales", "Product", "Lead_SA", "Admin"] as const)("%s melihat '+ Request SA' dan tombol membuka form baru", async (role) => {
    serve();
    const { user } = setup(role);
    await user.click(await screen.findByRole("button", { name: "+ Request SA" }));
    expect(router.push).toHaveBeenCalledWith("/projects/new");
  });

  it("SA tidak melihat '+ Request SA' (backend menolak SA membuat proyek)", async () => {
    serve();
    setup("SA");
    await screen.findByText("Alfa Cloud");
    expect(screen.queryByRole("button", { name: "+ Request SA" })).not.toBeInTheDocument();
  });
});

describe("Daftar proyek — memuat, kosong, error", () => {
  it("menampilkan skeleton saat memuat, tanpa teks jumlah", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.get(api("/projects"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope(proyek));
      }),
    );
    const { container } = setup("Lead_SA");
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Menampilkan/)).not.toBeInTheDocument();
    lepas();
    expect(await screen.findByText("Menampilkan 3 dari 3 proyek")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).not.toBeInTheDocument();
  });

  it.each([
    ["Sales", "Buat Request SA untuk memulai."],
    ["Product", "Buat Request SA untuk memulai."],
    ["SA", "Belum ada proyek yang tersedia."],
    ["Lead_SA", "Buat Request SA untuk memulai."],
    ["Admin", "Buat Request SA untuk memulai."],
  ] as const)("keadaan kosong untuk %s", async (role, petunjuk) => {
    serve([]);
    setup(role);
    expect(await screen.findByRole("heading", { name: "Belum ada proyek" })).toBeInTheDocument();
    expect(screen.getByText(petunjuk)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset Filter" })).not.toBeInTheDocument();
    expect(screen.getByText("Menampilkan 0 dari 0 proyek")).toBeInTheDocument();
  });

  it.each(SEMUA_PERAN)("%s: keadaan kosong saat sakelar aktif memakai 'Tidak ada proyek milik Anda'", async (role) => {
    server.use(
      http.get(api("/projects"), ({ request }) =>
        HttpResponse.json(
          successEnvelope(new URL(request.url).searchParams.get("involved") === "me" ? [] : proyek),
        ),
      ),
    );
    const { user } = setup(role);
    await screen.findByText("Alfa Cloud");
    await user.click(screen.getByRole("checkbox", { name: "Hanya proyek saya" }));

    expect(await screen.findByRole("heading", { name: "Tidak ada proyek milik Anda" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Belum ada proyek" })).not.toBeInTheDocument();
    expect(screen.getByText("Matikan sakelar 'Hanya proyek saya' untuk melihat semua proyek.")).toBeInTheDocument();
  });

  it("keadaan kosong tanpa sakelar tetap 'Belum ada proyek'", async () => {
    serve([]);
    setup("Lead_SA");
    expect(await screen.findByRole("heading", { name: "Belum ada proyek" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Tidak ada proyek milik Anda" })).not.toBeInTheDocument();
  });

  it("error server: pesan error (bukan 'Belum ada proyek'), coba lagi memuat ulang daftar", async () => {
    server.use(gagalLaluBerhasil("/projects", proyek));
    const { user } = setup("Lead_SA");

    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat daftar proyek.");
    expect(screen.queryByText("Belum ada proyek")).not.toBeInTheDocument();
    expect(screen.queryByText(/Menampilkan \d+ dari \d+ proyek/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Proyek", level: 1 })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(await screen.findByText("Alfa Cloud")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Daftar proyek — skor BANT pada kartu (#83)", () => {
  it("meneruskan bant_score ke kartu: Passed bila >= 60, not passed bila < 60, tanpa label bila null", async () => {
    serve([
      makeProject({ id_project: "id-1", project_name: "Lulus", customer_name: "PT L", bant_score: 72 }),
      makeProject({ id_project: "id-2", project_name: "Gagal", customer_name: "PT G", bant_score: 40 }),
      makeProject({ id_project: "id-3", project_name: "Belum", customer_name: "PT B", bant_score: null }),
    ]);
    setup("Lead_SA");

    expect(await screen.findByText("BANT Passed")).toBeInTheDocument();
    expect(screen.getByText("BANT not passed")).toBeInTheDocument();
    expect(screen.getAllByText(/^BANT/)).toHaveLength(2);
  });
});

describe("Daftar proyek — filter", () => {
  it("menampilkan kartu berisi nama, customer, status, DQ, dan badge Menunggu DQ", async () => {
    serve();
    setup("Lead_SA");
    const kartu = await screen.findByRole("button", { name: "Proyek Alfa Cloud - PT Satu" });
    expect(within(kartu).getByText("Assigned")).toBeInTheDocument();
    expect(within(kartu).getByText("DQ-1")).toBeInTheDocument();
    const kartuB = screen.getByRole("button", { name: "Proyek Beta Security - PT Dua" });
    expect(within(kartuB).getByText("Menunggu DQ")).toBeInTheDocument();
  });

  it("kartu Intake menampilkan qualification_state; di luar Intake tidak", async () => {
    serve([
      makeProject({ id_project: "i1", project_name: "Intake Satu", status: "Intake", qualification_state: "Need Clarification" }),
      makeProject({ id_project: "i2", project_name: "Sudah Lolos", status: "Awaiting Assignment", qualification_state: "Qualified" }),
    ]);
    setup("Lead_SA");
    const kartu = await screen.findByRole("button", { name: "Proyek Intake Satu - PT Contoh" });
    expect(within(kartu).getByText("Need Clarification")).toBeInTheDocument();
    const lolos = screen.getByRole("button", { name: "Proyek Sudah Lolos - PT Contoh" });
    expect(within(lolos).queryByText("Qualified")).not.toBeInTheDocument();
  });

  it.each(["In Progress", "Submitted", "Won", "Handed Over", "Closed", "On Hold"])(
    "filter status %s menyaring ke proyek berstatus itu",
    async (status) => {
      serve([
        makeProject({ id_project: "x1", project_name: "Cocok", status }),
        makeProject({ id_project: "x2", project_name: "Beda", status: "Assigned" }),
      ]);
      const { user } = setup("Lead_SA");
      await screen.findByText("Cocok");
      await user.selectOptions(screen.getByRole("combobox"), status);
      expect(screen.getByText("Cocok")).toBeInTheDocument();
      expect(screen.queryByText("Beda")).not.toBeInTheDocument();
    },
  );

  it("klik kartu menavigasi ke detail proyek", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await user.click(await screen.findByRole("button", { name: "Proyek Beta Security - PT Dua" }));
    expect(router.push).toHaveBeenCalledWith("/projects/id-bbb");
  });

  it("filter status menyaring sisi klien dan memperbarui jumlah", async () => {
    const urls = serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    await user.selectOptions(screen.getByRole("combobox"), "Lost");
    expect(screen.getByText("Gamma Data")).toBeInTheDocument();
    expect(screen.queryByText("Alfa Cloud")).not.toBeInTheDocument();
    expect(screen.getByText("Menampilkan 1 dari 3 proyek")).toBeInTheDocument();
    expect(urls).toHaveLength(1); // tidak ada request baru: filter sisi klien
  });

  it("dropdown status memuat semua status", async () => {
    serve();
    setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    const opsi = within(screen.getByRole("combobox")).getAllByRole("option").map((o) => o.textContent);
    expect(opsi).toEqual([
      "Semua Status", "Intake", "Awaiting Assignment", "Assigned", "In Progress", "Submitted",
      "Won", "Handed Over", "Closed", "Lost", "On Hold",
    ]);
  });

  it("pencarian menyaring nama proyek, case-insensitive", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    await user.type(screen.getByPlaceholderText("Cari nama proyek atau customer..."), "BETA");
    expect(screen.getByText("Beta Security")).toBeInTheDocument();
    expect(screen.queryByText("Alfa Cloud")).not.toBeInTheDocument();
  });

  it("pencarian menyaring nama customer dan id proyek", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    const cari = screen.getByPlaceholderText("Cari nama proyek atau customer...");
    await user.type(cari, "satu");
    expect(screen.getByText("Alfa Cloud")).toBeInTheDocument();
    expect(screen.getByText("Gamma Data")).toBeInTheDocument();
    expect(screen.queryByText("Beta Security")).not.toBeInTheDocument();
    await user.clear(cari);
    await user.type(cari, "id-ccc");
    expect(screen.getByText("Gamma Data")).toBeInTheDocument();
    expect(screen.queryByText("Alfa Cloud")).not.toBeInTheDocument();
  });

  it("pencarian hanya spasi tidak menyaring", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    await user.type(screen.getByPlaceholderText("Cari nama proyek atau customer..."), "   ");
    expect(screen.getByText("Menampilkan 3 dari 3 proyek")).toBeInTheDocument();
  });

  it("status + pencarian digabung (AND)", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    await user.selectOptions(screen.getByRole("combobox"), "Lost");
    await user.type(screen.getByPlaceholderText("Cari nama proyek atau customer..."), "alfa");
    expect(screen.getByRole("heading", { name: "Tidak ada hasil" })).toBeInTheDocument();
  });

  it("tidak ada hasil: pesan + Reset Filter mengembalikan semua", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Alfa Cloud");
    await user.type(screen.getByPlaceholderText("Cari nama proyek atau customer..."), "tidak-ada");
    expect(screen.getByRole("heading", { name: "Tidak ada hasil" })).toBeInTheDocument();
    expect(screen.getByText("Coba ubah kata kunci atau filter status.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset Filter" }));
    expect(screen.getByText("Menampilkan 3 dari 3 proyek")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Cari nama proyek atau customer...")).toHaveValue("");
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("proyek tanpa updated_at tetap tampil", async () => {
    serve([makeProject({ updated_at: null, project_name: "Tanpa Tanggal" })]);
    setup("Lead_SA");
    expect(await screen.findByText("Tanpa Tanggal")).toBeInTheDocument();
  });
});
