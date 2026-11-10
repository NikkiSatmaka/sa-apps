import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, router, server, successEnvelope } from "@/test";
import { NotificationBell } from "./NotificationBell";

function unread(count: number) {
  server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json(successEnvelope({ count }))));
}

describe("NotificationBell", () => {
  afterEach(() => vi.useRealTimers());

  it("menampilkan badge dan label aksesibel dengan jumlah belum dibaca", async () => {
    unread(3);
    renderWithProviders(<NotificationBell />, { role: "SA" });
    expect(await screen.findByRole("button", { name: "Notifikasi, 3 belum dibaca" })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("tanpa notifikasi belum dibaca: tanpa badge dan label polos", async () => {
    unread(0);
    renderWithProviders(<NotificationBell />, { role: "SA" });
    const tombol = await screen.findByRole("button", { name: "Notifikasi" });
    await waitFor(() => expect(tombol).toBeInTheDocument());
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("jumlah di atas 99 ditampilkan sebagai 99+", async () => {
    unread(150);
    renderWithProviders(<NotificationBell />, { role: "SA" });
    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("saat request gagal tetap tampil tanpa badge", async () => {
    server.use(http.get(api("/notifications/unread-count"), () => HttpResponse.json({ message: "x" }, { status: 500 })));
    renderWithProviders(<NotificationBell />, { role: "SA" });
    expect(await screen.findByRole("button", { name: "Notifikasi" })).toBeInTheDocument();
    expect(screen.queryByText("99+")).not.toBeInTheDocument();
  });

  it("klik membuka halaman /notifications", async () => {
    unread(1);
    const { user } = renderWithProviders(<NotificationBell />, { role: "SA" });
    await user.click(await screen.findByRole("button", { name: /Notifikasi/ }));
    expect(router.push).toHaveBeenCalledWith("/notifications");
  });

  it("memperbarui jumlah lewat polling tiap 30 detik", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    unread(1);
    renderWithProviders(<NotificationBell />, { role: "SA" });
    expect(await screen.findByRole("button", { name: "Notifikasi, 1 belum dibaca" })).toBeInTheDocument();

    unread(5);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(await screen.findByRole("button", { name: "Notifikasi, 5 belum dibaca" })).toBeInTheDocument();
  });
});
