import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { setOnline } from "@/test";
import { enqueueSubmission } from "@/lib/offline-queue";
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

  it("melepas listener saat unmount", () => {
    const { unmount } = render(<OfflineIndicator />);
    unmount();
    expect(() => act(() => setOnline(false))).not.toThrow();
  });
});
