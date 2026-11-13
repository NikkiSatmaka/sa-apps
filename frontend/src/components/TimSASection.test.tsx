import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, gagalLaluBerhasil, http, HttpResponse, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { makeAvailableSA } from "@/test/fixtures/operations";
import { makeSATambahan, makeTimSA, type TimSAFixture } from "@/test/fixtures/project-detail";
import { TimSASection } from "./TimSASection";

const URL_TIM = "/projects/p1/tim-sa";

const tim: TimSAFixture = makeTimSA({
  sa_utama: { id: "sa1", name: "Andi Utama", email: "andi@x" },
  sa_tambahan: [makeSATambahan({ id: "sa2", name: "Budi Tambahan", email: "budi@x" })],
});

const kandidat = [
  makeAvailableSA({ id: "sa1", name: "Andi Utama" }),
  makeAvailableSA({ id: "sa2", name: "Budi Tambahan" }),
  makeAvailableSA({ id: "sa3", name: "Cici Baru" }),
  makeAvailableSA({ id: "sa4", name: "Dedi Baru" }),
];

function serve(data: TimSAFixture = tim) {
  server.use(
    http.get(api(URL_TIM), () => HttpResponse.json(successEnvelope(data))),
    http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope(kandidat))),
  );
}

function setup(role?: Role) {
  return renderWithProviders(<TimSASection projectId="p1" />, role ? { role } : {});
}

const KONTROL = [
  "+ Tambah SA",
  "Ganti SA utama",
  "Jadikan SA utama",
  "Lepas",
];

describe("TimSASection — tampilan", () => {
  it.each(["Sales", "Product", "SA", "Lead_SA", "Admin"] as const)(
    "%s melihat SA utama dan SA tambahan",
    async (role) => {
      serve();
      setup(role);
      expect(await screen.findByRole("heading", { name: "Tim SA" })).toBeInTheDocument();
      const utama = screen.getByRole("listitem", { name: "SA utama: Andi Utama" });
      expect(within(utama).getByText("SA utama")).toBeInTheDocument();
      expect(within(utama).getByText("andi@x")).toBeInTheDocument();
      const tambahan = screen.getByRole("listitem", { name: "SA tambahan: Budi Tambahan" });
      expect(within(tambahan).getByText("SA tambahan")).toBeInTheDocument();
    },
  );

  it.each(["Sales", "Product", "SA"] as const)("%s tidak melihat kontrol kelola tim dan tidak memuat /sa/available", async (role) => {
    serve();
    let dipanggil = false;
    server.use(http.get(api("/sa/available"), () => { dipanggil = true; return HttpResponse.json(successEnvelope([])); }));
    setup(role);
    await screen.findByText("Andi Utama");
    for (const nama of KONTROL) {
      expect(screen.queryByRole("button", { name: new RegExp(nama) })).not.toBeInTheDocument();
    }
    expect(dipanggil).toBe(false);
  });

  it("tanpa SA tambahan: keterangan 'Belum ada SA tambahan'", async () => {
    serve(makeTimSA());
    setup("Sales");
    expect(await screen.findByText("Belum ada SA tambahan.")).toBeInTheDocument();
  });

  it("belum ada SA utama: pesan 'belum ditugaskan' dan tidak ada kontrol, bahkan untuk Lead_SA", async () => {
    serve(makeTimSA({ sa_utama: null }));
    setup("Lead_SA");
    expect(await screen.findByText("Belum ada SA utama. Tugaskan SA lewat assignment.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Tambah SA|Ganti SA utama/ })).not.toBeInTheDocument();
  });

  it("menampilkan skeleton saat memuat", () => {
    serve();
    const { container } = setup("Sales");
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("error memuat tampil sebagai alert dan bisa dicoba ulang", async () => {
    server.use(gagalLaluBerhasil(URL_TIM, tim));
    const { user } = setup("Sales");
    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat tim SA.");
    expect(screen.queryByText("Belum ada SA tambahan.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByText("Andi Utama")).toBeInTheDocument();
  });
});

describe("TimSASection — Lead_SA/Admin menambah SA tambahan", () => {
  it.each(["Lead_SA", "Admin"] as const)("%s: panel hanya menawarkan SA yang belum di tim, POST user_id, daftar dimuat ulang", async (role) => {
    let data = tim;
    let body: unknown;
    server.use(
      http.get(api(URL_TIM), () => HttpResponse.json(successEnvelope(data))),
      http.get(api("/sa/available"), () => HttpResponse.json(successEnvelope(kandidat))),
      http.post(api(URL_TIM), async ({ request }) => {
        body = await request.json();
        data = { ...tim, sa_tambahan: [...tim.sa_tambahan, makeSATambahan({ id: "sa3", name: "Cici Baru" })] };
        return HttpResponse.json(successEnvelope(data), { status: 201 });
      }),
    );
    const { user } = setup(role);
    await screen.findByText("Andi Utama");
    const toggle = screen.getByRole("button", { name: "+ Tambah SA" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Tambah ke tim" })).toBeDisabled();

    const select = await screen.findByLabelText("Pilih SA:");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Cici Baru" })).toBeInTheDocument());
    const opsi = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(opsi).not.toContain("Andi Utama");
    expect(opsi).not.toContain("Budi Tambahan");

    await user.selectOptions(select, "sa3");
    await user.click(screen.getByRole("button", { name: "Tambah ke tim" }));

    expect(await screen.findByRole("listitem", { name: "SA tambahan: Cici Baru" })).toBeInTheDocument();
    expect(body).toEqual({ user_id: "sa3" });
    expect(screen.queryByLabelText("Pilih SA:")).not.toBeInTheDocument();
  });

  it("gagal menambah: pesan server di alert, panel tetap terbuka", async () => {
    serve();
    server.use(http.post(api(URL_TIM), () => HttpResponse.json(errorEnvelope("Sudah anggota tim"), { status: 409 })));
    const { user } = setup("Lead_SA");
    await screen.findByText("Andi Utama");
    await user.click(screen.getByRole("button", { name: "+ Tambah SA" }));
    const select = await screen.findByLabelText("Pilih SA:");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Cici Baru" })).toBeInTheDocument());
    await user.selectOptions(select, "sa3");
    await user.click(screen.getByRole("button", { name: "Tambah ke tim" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sudah anggota tim");
    expect(screen.getByLabelText("Pilih SA:")).toBeInTheDocument();
  });

  it("tombol batal menutup panel", async () => {
    serve();
    const { user } = setup("Lead_SA");
    await screen.findByText("Andi Utama");
    await user.click(screen.getByRole("button", { name: "+ Tambah SA" }));
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByLabelText("Pilih SA:")).not.toBeInTheDocument();
  });
});

describe("TimSASection — Lead_SA/Admin melepas SA tambahan", () => {
  it("konfirmasi lalu DELETE; daftar dimuat ulang", async () => {
    let data = tim;
    server.use(
      http.get(api(URL_TIM), () => HttpResponse.json(successEnvelope(data))),
      http.delete(api(`${URL_TIM}/sa2`), () => {
        data = makeTimSA({ sa_utama: tim.sa_utama });
        return HttpResponse.json(successEnvelope(data));
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = setup("Lead_SA");
    await screen.findByText("Budi Tambahan");
    await user.click(screen.getByRole("button", { name: "Lepas Budi Tambahan" }));
    expect(window.confirm).toHaveBeenCalledWith("Lepas Budi Tambahan dari tim SA proyek ini?");
    expect(await screen.findByText("Belum ada SA tambahan.")).toBeInTheDocument();
  });

  it("batal konfirmasi tidak mengirim DELETE", async () => {
    serve();
    let jumlah = 0;
    server.use(http.delete(api(`${URL_TIM}/sa2`), () => { jumlah++; return HttpResponse.json(successEnvelope(tim)); }));
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { user } = setup("Admin");
    await screen.findByText("Budi Tambahan");
    await user.click(screen.getByRole("button", { name: "Lepas Budi Tambahan" }));
    expect(jumlah).toBe(0);
  });

  it("gagal melepas: pesan server di alert", async () => {
    serve();
    server.use(http.delete(api(`${URL_TIM}/sa2`), () => HttpResponse.json(errorEnvelope("Gagal melepas"), { status: 409 })));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = setup("Lead_SA");
    await screen.findByText("Budi Tambahan");
    await user.click(screen.getByRole("button", { name: "Lepas Budi Tambahan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal melepas");
  });

  it("SA utama tidak punya tombol Lepas (minimal satu SA)", async () => {
    serve();
    setup("Lead_SA");
    await screen.findByText("Andi Utama");
    expect(screen.queryByRole("button", { name: "Lepas Andi Utama" })).not.toBeInTheDocument();
    expect(screen.getByText("Project minimal punya satu SA.")).toBeInTheDocument();
  });
});

describe("TimSASection — Lead_SA/Admin mengganti SA utama", () => {
  it("jadikan SA tambahan sebagai SA utama: PUT tanpa mempertahankan SA lama", async () => {
    let data = tim;
    let body: unknown;
    server.use(
      http.get(api(URL_TIM), () => HttpResponse.json(successEnvelope(data))),
      http.put(api(`${URL_TIM}/utama`), async ({ request }) => {
        body = await request.json();
        data = makeTimSA({ sa_utama: { id: "sa2", name: "Budi Tambahan", email: "budi@x" } });
        return HttpResponse.json(successEnvelope(data));
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = setup("Lead_SA");
    await screen.findByText("Budi Tambahan");
    await user.click(screen.getByRole("button", { name: "Jadikan Budi Tambahan SA utama" }));
    expect(await screen.findByRole("listitem", { name: "SA utama: Budi Tambahan" })).toBeInTheDocument();
    expect(body).toEqual({ user_id: "sa2", pertahankan_sebagai_tambahan: false });
  });

  it("ganti SA utama ke SA baru lewat panel, dengan opsi mempertahankan SA lama", async () => {
    let body: unknown;
    serve();
    server.use(
      http.put(api(`${URL_TIM}/utama`), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope(tim));
      }),
    );
    const { user } = setup("Admin");
    await screen.findByText("Andi Utama");
    const buka = screen.getByRole("button", { name: "Ganti SA utama" });
    expect(buka).toHaveAttribute("aria-expanded", "false");
    await user.click(buka);
    expect(screen.getByRole("button", { name: "Simpan SA utama" })).toBeDisabled();
    const select = await screen.findByLabelText("SA utama baru:");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Dedi Baru" })).toBeInTheDocument());
    expect(within(select).queryByRole("option", { name: "Andi Utama" })).not.toBeInTheDocument();
    await user.selectOptions(select, "sa4");
    await user.click(screen.getByLabelText("Pertahankan Andi Utama sebagai SA tambahan"));
    await user.click(screen.getByRole("button", { name: "Simpan SA utama" }));
    await waitFor(() => expect(body).toEqual({ user_id: "sa4", pertahankan_sebagai_tambahan: true }));
    await waitFor(() => expect(screen.queryByLabelText("SA utama baru:")).not.toBeInTheDocument());
  });

  it("gagal mengganti: pesan server di alert", async () => {
    serve();
    server.use(http.put(api(`${URL_TIM}/utama`), () => HttpResponse.json(errorEnvelope("Role tidak valid"), { status: 400 })));
    const { user } = setup("Lead_SA");
    await screen.findByText("Andi Utama");
    await user.click(screen.getByRole("button", { name: "Ganti SA utama" }));
    const select = await screen.findByLabelText("SA utama baru:");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Dedi Baru" })).toBeInTheDocument());
    await user.selectOptions(select, "sa4");
    await user.click(screen.getByRole("button", { name: "Simpan SA utama" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Role tidak valid");
  });
});
