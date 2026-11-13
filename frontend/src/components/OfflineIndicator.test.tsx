import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, api, http, server, setOnline } from "@/test";
import { enqueueSubmission, getQueuedItems, syncOfflineQueue } from "@/lib/offline-queue";
import { OfflineIndicator } from "./OfflineIndicator";

describe("OfflineIndicator", () => {
  it("online dan antrean kosong: tidak menampilkan apa pun", () => {
    render(<OfflineIndicator />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("menampilkan banner saat awalnya sudah offline", () => {
    setOnline(false, false);
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent("Anda sedang offline");
  });

  it("banner muncul saat event offline dan hilang saat event online", () => {
    render(<OfflineIndicator />);
    act(() => setOnline(false));
    expect(screen.getByRole("status")).toHaveTextContent(/Anda sedang offline/);
    act(() => setOnline(true));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("menampilkan jumlah item menunggu sinkronisasi dari antrean awal", () => {
    enqueueSubmission("/projects", "POST", { a: 1 });
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent("Menunggu Sinkronisasi (1 item)");
  });

  it("memperbarui jumlah saat antrean berubah (offline-queue-updated)", () => {
    render(<OfflineIndicator />);
    expect(screen.queryByText(/Menunggu Sinkronisasi/)).not.toBeInTheDocument();
    act(() => void enqueueSubmission("/projects", "POST", { a: 1 }));
    act(() => void enqueueSubmission("/projects", "POST", { a: 2 }));
    expect(screen.getByText(/Menunggu Sinkronisasi \(2 item\)/)).toBeInTheDocument();
  });

  it("offline dengan antrean menampilkan kedua indikator", () => {
    enqueueSubmission("/projects", "POST", { a: 1 });
    setOnline(false, false);
    render(<OfflineIndicator />);
    expect(screen.getAllByRole("status")).toHaveLength(2);
  });

  it("item gagal permanen: peringatan (alert) terpisah dari 'Menunggu Sinkronisasi', bisa dibuang pengguna", async () => {
    server.use(http.post(api("/activity-logs"), () => HttpResponse.json({}, { status: 422 })));
    enqueueSubmission(api("/activity-logs"), "POST", { a: 1 });
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent("Menunggu Sinkronisasi (1 item)");

    await act(async () => void (await syncOfflineQueue()));

    expect(screen.getByRole("alert")).toHaveTextContent("1 item gagal disinkronkan");
    expect(screen.queryByText(/Menunggu Sinkronisasi/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Buang" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(getQueuedItems()).toEqual([]);
  });

  it("melepas listener saat unmount", () => {
    const { unmount } = render(<OfflineIndicator />);
    unmount();
    expect(() => act(() => setOnline(false))).not.toThrow();
  });
});
