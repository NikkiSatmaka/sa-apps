import { act, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import { makeDocumentsData } from "@/test/fixtures/requirement";
import { RequirementRegenerateSection } from "./RequirementRegenerateSection";

type Status = "pending" | "ready" | "failed" | null;

/** Handler status yang bisa diubah di tengah test; menghitung jumlah permintaan (polling). */
function useStatus(initial: Status, canRegenerate = true) {
  const state = { status: initial, canRegenerate, hits: 0 };
  server.use(
    http.get(api("/projects/:id/documents"), () => {
      state.hits += 1;
      return HttpResponse.json(
        successEnvelope(
          makeDocumentsData([], {
            requirement_generation_status: state.status,
            can_regenerate_requirement: state.canRegenerate,
          })
        )
      );
    })
  );
  return state;
}

function useRegenerate(result: "ok" | { status: number; body: unknown }) {
  const calls = { count: 0 };
  server.use(
    http.post(api("/projects/:id/requirement/regenerate"), () => {
      calls.count += 1;
      if (result === "ok") return HttpResponse.json(successEnvelope(null), { status: 202 });
      return HttpResponse.json(result.body as object, { status: result.status });
    })
  );
  return calls;
}

describe("RequirementRegenerateSection", () => {
  it("proyek belum punya Requirement (status null): tidak menampilkan apa pun", async () => {
    const state = useStatus(null);
    const { container } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
    await waitFor(() => expect(state.hits).toBe(1));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("error memuat status: tidak menampilkan apa pun", async () => {
    server.use(
      http.get(api("/projects/:id/documents"), () =>
        HttpResponse.json(errorEnvelope("gagal"), { status: 500 })
      )
    );
    const { container } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(container).toBeEmptyDOMElement();
  });

  describe("ready", () => {
    it("peran berhak: tombol Generate ulang mengirim POST lalu memuat ulang status", async () => {
      const state = useStatus("ready");
      const calls = useRegenerate("ok");
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);

      expect(await screen.findByText(/Generate ulang menimpa butir Requirement/)).toBeInTheDocument();
      const hitsBefore = state.hits;
      await user.click(screen.getByRole("button", { name: "Generate ulang" }));

      await waitFor(() => expect(calls.count).toBe(1));
      await waitFor(() => expect(state.hits).toBeGreaterThan(hitsBefore));
    });

    it("peran tidak berhak: tidak menampilkan tombol", async () => {
      const state = useStatus("ready", false);
      const { container } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      await waitFor(() => expect(state.hits).toBe(1));
      await act(async () => {});
      expect(container).toBeEmptyDOMElement();
    });

    it("gagal memulai: menampilkan pesan detail backend dan tombol aktif kembali", async () => {
      useStatus("ready");
      useRegenerate({ status: 409, body: { detail: "Generate sedang berjalan" } });
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      await user.click(await screen.findByRole("button", { name: "Generate ulang" }));
      expect(await screen.findByText("Generate sedang berjalan")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Generate ulang" })).toBeEnabled();
    });

    it("selama mengirim: tombol menampilkan Memulai... dan nonaktif", async () => {
      useStatus("ready");
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      server.use(
        http.post(api("/projects/:id/requirement/regenerate"), async () => {
          await gate;
          return HttpResponse.json(successEnvelope(null), { status: 202 });
        })
      );
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      await user.click(await screen.findByRole("button", { name: "Generate ulang" }));
      expect(await screen.findByRole("button", { name: "Memulai..." })).toBeDisabled();
      release();
      await waitFor(() => expect(screen.getByRole("button", { name: "Generate ulang" })).toBeEnabled());
    });
  });

  describe("failed", () => {
    it("peran berhak: alert gagal + Coba lagi memanggil regenerate", async () => {
      useStatus("failed");
      const calls = useRegenerate("ok");
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Requirement gagal dibuat.");
      expect(alert).not.toHaveTextContent("Hubungi SA yang ditugaskan");
      await user.click(screen.getByRole("button", { name: "Coba lagi" }));
      await waitFor(() => expect(calls.count).toBe(1));
    });

    it("peran tidak berhak: tanpa tombol, ada arahan menghubungi pihak berwenang", async () => {
      useStatus("failed", false);
      renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Hubungi SA yang ditugaskan, Lead SA, atau Admin.");
      expect(screen.queryByRole("button", { name: "Coba lagi" })).not.toBeInTheDocument();
    });

    it("Coba lagi gagal: pesan error muncul di dalam alert; selama proses tombol Memulai...", async () => {
      useStatus("failed");
      useRegenerate({ status: 500, body: { message: "Layanan AI down" } });
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      await user.click(await screen.findByRole("button", { name: "Coba lagi" }));
      expect(await screen.findByText("Layanan AI down")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Coba lagi" })).toBeEnabled();
    });

    it("Coba lagi: status berubah ke pending dan pesan sedang dibuat tampil", async () => {
      const state = useStatus("failed");
      server.use(
        http.post(api("/projects/:id/requirement/regenerate"), () => {
          state.status = "pending";
          return HttpResponse.json(successEnvelope(null), { status: 202 });
        })
      );
      const { user } = renderWithProviders(<RequirementRegenerateSection projectId="p1" />);
      await user.click(await screen.findByRole("button", { name: "Coba lagi" }));
      expect(await screen.findByRole("status")).toHaveTextContent("Requirement sedang dibuat");
    });
  });

  describe("pending (polling dengan fake timers)", () => {
    // SWR mengikat refreshInterval ke setTimeout; fake timers + shouldAdvanceTime agar MSW/undici tetap jalan.
    function renderFake(onChanged?: () => void) {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      render(
        <SWRConfig
          value={{ provider: () => new Map(), dedupingInterval: 0, errorRetryCount: 0, shouldRetryOnError: false }}
        >
          <RequirementRegenerateSection projectId="p1" onChanged={onChanged} />
        </SWRConfig>
      );
    }

    it("menampilkan status, polling tiap 3 detik, lalu berhenti dan memanggil onChanged saat selesai", async () => {
      const state = useStatus("pending");
      const onChanged = vi.fn();
      renderFake(onChanged);

      expect(await screen.findByRole("status")).toHaveTextContent(
        "Requirement sedang dibuat… Halaman ini diperbarui otomatis saat selesai."
      );
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(state.hits).toBe(1);

      // Belum 3 detik: tidak ada polling baru
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(state.hits).toBe(1);

      // Sesudah 3 detik: polling pertama, masih pending
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1200);
      });
      await waitFor(() => expect(state.hits).toBe(2));
      expect(onChanged).not.toHaveBeenCalled();

      // Backend selesai; polling berikutnya mengubah tampilan dan memicu onChanged tepat sekali
      state.status = "ready";
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3200);
      });
      await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
      expect(screen.queryByText(/sedang dibuat/)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Generate ulang" })).toBeInTheDocument();

      // Polling berhenti setelah tidak pending
      const hits = state.hits;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });
      expect(state.hits).toBe(hits);
      expect(onChanged).toHaveBeenCalledTimes(1);
    });

    it("pending lalu gagal: menampilkan alert gagal dan onChanged tetap dipanggil", async () => {
      const state = useStatus("pending");
      const onChanged = vi.fn();
      renderFake(onChanged);
      await screen.findByRole("status");

      state.status = "failed";
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3200);
      });
      expect(await screen.findByRole("alert")).toHaveTextContent("Requirement gagal dibuat.");
      expect(onChanged).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
    });

    it("status ready sejak awal tidak memicu polling maupun onChanged", async () => {
      const state = useStatus("ready");
      const onChanged = vi.fn();
      renderFake(onChanged);
      await screen.findByRole("button", { name: "Generate ulang" });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9000);
      });
      expect(state.hits).toBe(1);
      expect(onChanged).not.toHaveBeenCalled();
    });
  });
});
