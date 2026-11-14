import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mutate } from "swr";
import { http, HttpResponse, api, renderWithProviders, router, seedAuth, server, successEnvelope } from "@/test";
import { makeNotification, makePaginatedNotifications } from "@/test/fixtures/notifications";
import type { NotificationEventType } from "@/lib/api/notifications";
import NotificationsPage from "./page";

const NOW = new Date("2025-06-15T12:00:00Z");

function list(items = [makeNotification()], extra: Record<string, unknown> = {}) {
  server.use(
    http.get(api("/notifications"), () =>
      HttpResponse.json(successEnvelope({ ...makePaginatedNotifications(items), ...extra })),
    ),
  );
}

afterEach(async () => {
  // cache SWR global (dipakai test tanpa SWRConfig) dibersihkan
  await mutate(() => true, undefined, { revalidate: false });
});

describe("Halaman Notifikasi — keadaan", () => {
  it("memuat: menampilkan 5 skeleton", () => {
    server.use(http.get(api("/notifications"), () => new Promise(() => {})));
    const { container } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(5);
  });

  it("kosong: 'Tidak ada notifikasi'", async () => {
    list([]);
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(await screen.findByText("Tidak ada notifikasi")).toBeInTheDocument();
  });

  it("error: pesan gagal memuat tanpa daftar", async () => {
    server.use(http.get(api("/notifications"), () => HttpResponse.json({ message: "x" }, { status: 500 })));
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(await screen.findByText("Gagal memuat notifikasi. Silakan coba lagi.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("berisi: membedakan belum dibaca (label & titik) dan sudah dibaca", async () => {
    list([
      makeNotification({ id: "n1", message: "Belum dibaca", status: "sent" }),
      makeNotification({ id: "n2", message: "Sudah dibaca", status: "read" }),
    ]);
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(await screen.findByRole("button", { name: "Belum dibaca: Belum dibaca" })).toBeInTheDocument();
    const dibaca = screen.getByRole("button", { name: "Sudah dibaca" });
    expect(dibaca).toBeInTheDocument();
    expect(screen.getByText("Sudah dibaca")).toHaveClass("font-normal");
    expect(screen.getByText("Belum dibaca")).toHaveClass("font-semibold");
  });
});

describe("Halaman Notifikasi — waktu relatif", () => {
  it.each([
    ["2025-06-15T11:59:30Z", "Baru saja"],
    ["2025-06-15T11:55:00Z", "5 menit lalu"],
    ["2025-06-15T09:00:00Z", "3 jam lalu"],
    ["2025-06-13T12:00:00Z", "2 hari lalu"],
  ])("%s → %s", async (createdAt, teks) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    list([makeNotification({ created_at: createdAt })]);
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(await screen.findByText(teks)).toBeInTheDocument();
  });

  it("lebih dari seminggu menampilkan tanggal lengkap", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    list([makeNotification({ created_at: "2025-01-02T10:00:00Z" })]);
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    expect(await screen.findByText(/2025/)).toBeInTheDocument();
  });
});

describe("Halaman Notifikasi — klik", () => {
  const kasus: [NotificationEventType, string | null, Record<string, unknown> | null, string][] = [
    ["assignment", "p1", null, "/projects/p1"],
    ["status_change", "p1", null, "/projects/p1"],
    ["sla_reminder", "p1", null, "/projects/p1"],
    ["sla_escalation", "p1", null, "/projects/p1"],
    ["handover", "p1", null, "/projects/p1"],
    ["komentar", "p1", null, "/projects/p1"],
    ["doc_ready", "p1", { document_id: "d1" }, "/projects/p1/documents"],
    ["doc_ready", "p1", null, "/projects/p1"],
    ["assignment", null, null, "/dashboard"],
  ];

  it.each(kasus)("%s (ref=%s, metadata=%j) membuka %s", async (event_type, reference_id, metadata, tujuan) => {
    list([makeNotification({ event_type, reference_id, metadata, status: "read", message: "Pesan" })]);
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: "Pesan" }));
    expect(router.push).toHaveBeenCalledWith(tujuan);
  });

  it("tipe event tak dikenal dengan reference_id tetap membuka proyek", async () => {
    list([makeNotification({ event_type: "baru" as never, reference_id: "p9", status: "read", message: "Aneh" })]);
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: "Aneh" }));
    expect(router.push).toHaveBeenCalledWith("/projects/p9");
  });

  it("notifikasi belum dibaca: menandai dibaca lewat PATCH lalu berpindah halaman", async () => {
    const patched: string[] = [];
    server.use(
      http.patch(api("/notifications/:id/read"), ({ params }) => {
        patched.push(String(params.id));
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    list([makeNotification({ id: "n-1", status: "sent", message: "Baru" })]);
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: "Belum dibaca: Baru" }));

    expect(patched).toEqual(["n-1"]);
    expect(router.push).toHaveBeenCalledWith("/projects/11111111-1111-4111-8111-111111111111");
  });

  it("notifikasi yang sudah dibaca tidak memanggil PATCH lagi", async () => {
    let patched = 0;
    server.use(
      http.patch(api("/notifications/:id/read"), () => {
        patched++;
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    list([makeNotification({ status: "read", message: "Lama" })]);
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: "Lama" }));
    expect(patched).toBe(0);
    expect(router.push).toHaveBeenCalled();
  });

  it("gagal menandai dibaca tidak menghalangi navigasi", async () => {
    server.use(http.patch(api("/notifications/:id/read"), () => HttpResponse.json({ message: "x" }, { status: 500 })));
    list([makeNotification({ status: "sent", message: "Gagal" })]);
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: "Belum dibaca: Gagal" }));
    expect(router.push).toHaveBeenCalledWith("/projects/11111111-1111-4111-8111-111111111111");
  });

  it("setelah ditandai dibaca, daftar dimuat ulang dari server (cache SWR aplikasi nyata)", async () => {
    // Aplikasi nyata tanpa SWRConfig: `mutate` global menyasar cache default, jadi render tanpa wrapper.
    seedAuth("SA");
    let status: "sent" | "read" = "sent";
    let gets = 0;
    server.use(
      http.get(api("/notifications"), () => {
        gets++;
        return HttpResponse.json(successEnvelope(makePaginatedNotifications([makeNotification({ status, message: "Segarkan" })])));
      }),
      http.patch(api("/notifications/:id/read"), () => {
        status = "read";
        return HttpResponse.json(successEnvelope(null));
      }),
    );
    const user = userEvent.setup();
    render(<NotificationsPage />);
    await user.click(await screen.findByRole("button", { name: "Belum dibaca: Segarkan" }));
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
    expect(await screen.findByRole("button", { name: "Segarkan" })).toBeInTheDocument();
  });
});

describe("Halaman Notifikasi — pagination", () => {
  it("satu halaman: tanpa kontrol pagination", async () => {
    list();
    renderWithProviders(<NotificationsPage />, { role: "SA" });
    await screen.findByRole("list");
    expect(screen.queryByRole("button", { name: "Halaman berikutnya" })).not.toBeInTheDocument();
  });

  it("banyak halaman: Next/Previous meminta halaman berikutnya dan batas dihormati", async () => {
    const pages: string[] = [];
    server.use(
      http.get(api("/notifications"), ({ request }) => {
        const url = new URL(request.url);
        pages.push(`${url.searchParams.get("page")}/${url.searchParams.get("per_page")}`);
        const page = Number(url.searchParams.get("page"));
        return HttpResponse.json(
          successEnvelope({
            ...makePaginatedNotifications([makeNotification({ message: `Halaman ${page}`, status: "read" })]),
            page,
            total: 40,
            total_pages: 2,
          }),
        );
      }),
    );
    const { user } = renderWithProviders(<NotificationsPage />, { role: "SA" });

    expect(await screen.findByText("Halaman 1 dari 2 (40 notifikasi)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Halaman sebelumnya" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Halaman berikutnya" }));
    expect(await screen.findByText("Halaman 2 dari 2 (40 notifikasi)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Halaman berikutnya" })).toBeDisabled();
    expect(pages).toEqual(["1/20", "2/20"]);

    await user.click(screen.getByRole("button", { name: "Halaman sebelumnya" }));
    expect(await screen.findByText("Halaman 1 dari 2 (40 notifikasi)")).toBeInTheDocument();
  });
});
