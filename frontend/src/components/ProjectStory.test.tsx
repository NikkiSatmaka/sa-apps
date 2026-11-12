import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { makeActivityLog, makeStoryPage } from "@/test/fixtures/operations";
import { ProjectStory } from "./ProjectStory";

function setup() {
  return renderWithProviders(<ProjectStory projectId="p-1" />, { role: "SA" });
}

function recordStoryRequests(page: () => unknown) {
  const urls: URL[] = [];
  server.use(
    http.get(api("/projects/:id/story"), ({ request }) => {
      const url = new URL(request.url);
      urls.push(url);
      return HttpResponse.json(successEnvelope(page()));
    })
  );
  return urls;
}

describe("ProjectStory — data", () => {
  it("menampilkan skeleton lalu daftar log dengan kategori, fase, durasi, dan catatan", async () => {
    const { container } = setup();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
    expect(screen.getByText("Assessment", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Pre-Implementation")).toBeInTheDocument();
    expect(screen.getByText("2 jam")).toBeInTheDocument();
    expect(screen.getByText(/2025/)).toBeInTheDocument(); // tanggal terformat
  });

  it("meminta halaman 1 dengan page_size 20 untuk proyek yang benar", async () => {
    const urls = recordStoryRequests(() => makeStoryPage());
    setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    expect(urls[0].pathname).toBe("/api/v1/projects/p-1/story");
    expect(urls[0].searchParams.get("page")).toBe("1");
    expect(urls[0].searchParams.get("page_size")).toBe("20");
    expect(urls[0].searchParams.has("category")).toBe(false);
  });

  it("menampilkan hasil AI polishing: poin diskusi dan action item dengan PIC", async () => {
    server.use(
      http.get(api("/projects/:id/story"), () =>
        HttpResponse.json(
          successEnvelope(
            makeStoryPage([
              makeActivityLog({
                ai_polished_notes: {
                  discussion_points: ["Skema lisensi", "Timeline PoC"],
                  action_items: [{ description: "Kirim proposal", pic: "Budi" }, { description: "Jadwalkan demo" }],
                },
              }),
            ])
          )
        )
      )
    );
    setup();
    expect(await screen.findByText("Poin Diskusi")).toBeInTheDocument();
    expect(screen.getByText("Skema lisensi")).toBeInTheDocument();
    expect(screen.getByText("Action Item")).toBeInTheDocument();
    expect(screen.getByText(/Kirim proposal/)).toBeInTheDocument();
    expect(screen.getByText("(PIC: Budi)")).toBeInTheDocument();
    expect(screen.getByText(/Jadwalkan demo/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Polish Ulang" })).not.toBeInTheDocument();
  });

  it("hasil polishing tanpa poin/action item tidak menampilkan bagian kosong", async () => {
    server.use(
      http.get(api("/projects/:id/story"), () =>
        HttpResponse.json(successEnvelope(makeStoryPage([makeActivityLog({ ai_polished_notes: { discussion_points: [], action_items: [] } })])))
      )
    );
    setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    expect(screen.queryByText("Poin Diskusi")).not.toBeInTheDocument();
    expect(screen.queryByText("Action Item")).not.toBeInTheDocument();
  });

  it("log tanpa fase tidak menampilkan lencana fase", async () => {
    server.use(http.get(api("/projects/:id/story"), () => HttpResponse.json(successEnvelope(makeStoryPage([makeActivityLog({ project_phase: null })])))));
    setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    expect(screen.queryByText("Pre-Implementation")).not.toBeInTheDocument();
  });

  it("keadaan kosong tanpa filter", async () => {
    server.use(http.get(api("/projects/:id/story"), () => HttpResponse.json(successEnvelope(makeStoryPage([])))));
    setup();
    expect(await screen.findByText("Belum ada activity log untuk proyek ini.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
  });

  it("error server menampilkan pesan gagal memuat", async () => {
    server.use(http.get(api("/projects/:id/story"), () => HttpResponse.json(errorEnvelope("Proyek tidak ditemukan"), { status: 404 })));
    setup();
    expect(await screen.findByText("Gagal memuat data: Proyek tidak ditemukan")).toBeInTheDocument();
  });
});

describe("ProjectStory — filter", () => {
  it("filter kategori mengirim parameter category dan mengosongkannya lewat Reset", async () => {
    const urls = recordStoryRequests(() => makeStoryPage());
    const { user } = setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    await user.selectOptions(screen.getByLabelText("Kategori"), "Customer Meeting");
    await waitFor(() => expect(urls.at(-1)!.searchParams.get("category")).toBe("Customer Meeting"));

    await user.click(await screen.findByRole("button", { name: "Reset" }));
    expect(screen.getByLabelText("Kategori")).toHaveValue("");
    await waitFor(() => expect(urls.at(-1)!.searchParams.has("category")).toBe(false));
  });

  it("filter tanggal mengirim date_from awal hari dan date_to akhir hari", async () => {
    const urls = recordStoryRequests(() => makeStoryPage());
    setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    fireEvent.change(screen.getByLabelText("Dari"), { target: { value: "2025-03-01" } });
    fireEvent.change(screen.getByLabelText("Sampai"), { target: { value: "2025-03-31" } });
    await waitFor(() => {
      const last = urls.at(-1)!;
      expect(last.searchParams.get("date_from")).toBe("2025-03-01T00:00:00");
      expect(last.searchParams.get("date_to")).toBe("2025-03-31T23:59:59");
    });
  });

  it("keadaan kosong dengan filter menampilkan pesan khusus filter", async () => {
    server.use(http.get(api("/projects/:id/story"), () => HttpResponse.json(successEnvelope(makeStoryPage([])))));
    const { user } = setup();
    await screen.findByText("Belum ada activity log untuk proyek ini.");
    await user.selectOptions(screen.getByLabelText("Kategori"), "Assessment");
    expect(await screen.findByText("Tidak ada activity log yang cocok dengan filter.")).toBeInTheDocument();
  });
});

describe("ProjectStory — pagination", () => {
  const pageResponse = (page: number) =>
    makeStoryPage([makeActivityLog({ id_log: `log-${page}`, raw_notes: `Catatan halaman ${page}` })], {
      total: 45, page, total_pages: 3,
    });

  it("tidak menampilkan pagination untuk satu halaman", async () => {
    setup();
    await screen.findByText("Diskusi kebutuhan dengan customer");
    expect(screen.queryByText(/Halaman 1 dari/)).not.toBeInTheDocument();
  });

  it("navigasi Selanjutnya/Sebelumnya meminta halaman terkait dan membatasi di ujung", async () => {
    const urls: string[] = [];
    server.use(
      http.get(api("/projects/:id/story"), ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        urls.push(String(page));
        return HttpResponse.json(successEnvelope(pageResponse(page)));
      })
    );
    const { user } = setup();
    expect(await screen.findByText("Catatan halaman 1")).toBeInTheDocument();
    expect(screen.getByText("Halaman 1 dari 3 (45 item)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sebelumnya/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Selanjutnya/ }));
    expect(await screen.findByText("Catatan halaman 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Selanjutnya/ }));
    expect(await screen.findByText("Catatan halaman 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Selanjutnya/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Sebelumnya/ }));
    expect(await screen.findByText("Catatan halaman 2")).toBeInTheDocument();
    expect(urls).toEqual(expect.arrayContaining(["1", "2", "3"]));
  });

  it("mengubah filter mengembalikan ke halaman 1", async () => {
    const pages: number[] = [];
    server.use(
      http.get(api("/projects/:id/story"), ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        pages.push(page);
        return HttpResponse.json(successEnvelope(pageResponse(page)));
      })
    );
    const { user } = setup();
    await screen.findByText("Catatan halaman 1");
    await user.click(screen.getByRole("button", { name: /Selanjutnya/ }));
    await screen.findByText("Catatan halaman 2");
    await user.selectOptions(screen.getByLabelText("Kategori"), "Assessment");
    expect(await screen.findByText("Halaman 1 dari 3 (45 item)")).toBeInTheDocument();
    expect(pages.at(-1)).toBe(1);
  });
});

describe("ProjectStory — Sales PIC (read-only, keputusan 2026-11-10)", () => {
  it("Sales membaca Story tetapi tidak melihat tombol Polish Ulang (hak TULIS tidak ada)", async () => {
    renderWithProviders(<ProjectStory projectId="p-1" />, { role: "Sales" });
    expect(await screen.findByText("Diskusi kebutuhan dengan customer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Polish Ulang" })).not.toBeInTheDocument();
  });
});

describe("ProjectStory — Polish Ulang", () => {
  it("sukses: POST polish, toast sukses, dan daftar dimuat ulang", async () => {
    let polished = false;
    let loads = 0;
    server.use(
      http.get(api("/projects/:id/story"), () => {
        loads++;
        return HttpResponse.json(
          successEnvelope(makeStoryPage([makeActivityLog({ ai_polished_notes: polished ? { discussion_points: ["Hasil polish"], action_items: [] } : null })]))
        );
      }),
      http.post(api("/activity-logs/:id/polish"), ({ params }) => {
        expect(params.id).toBe("log-1");
        polished = true;
        return HttpResponse.json(successEnvelope({}));
      })
    );
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Polish Ulang" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI polishing berhasil");
    expect(await screen.findByText("Hasil polish")).toBeInTheDocument();
    expect(loads).toBeGreaterThan(1);
    expect(screen.queryByRole("button", { name: "Polish Ulang" })).not.toBeInTheDocument();
  });

  it("menampilkan 'Memproses...' dan menonaktifkan tombol selama request", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(http.post(api("/activity-logs/:id/polish"), async () => { await gate; return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Polish Ulang" }));
    expect(await screen.findByRole("button", { name: "Memproses..." })).toBeDisabled();
    release();
    await screen.findByText("AI polishing berhasil");
  });

  it("error server: toast error dengan pesan backend", async () => {
    server.use(http.post(api("/activity-logs/:id/polish"), () => HttpResponse.json(errorEnvelope("Layanan AI tidak tersedia"), { status: 503 })));
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Polish Ulang" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Layanan AI tidak tersedia");
    expect(screen.getByRole("button", { name: "Polish Ulang" })).toBeEnabled();
  });

  it("toast hilang setelah 3 detik", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Polish Ulang" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
