import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useToastStore } from "@/store/toast";
import { ToastContainer } from "./Toast";

const show = (type: "success" | "error" | "info", msg: string) =>
  act(() => useToastStore.getState().showToast(type, msg));

describe("ToastContainer", () => {
  afterEach(() => vi.useRealTimers());

  it("tidak merender apa pun saat tidak ada toast", () => {
    const { container } = render(<ToastContainer />);
    expect(container).toBeEmptyDOMElement();
  });

  it("menampilkan toast sukses, error, dan info sebagai alert dengan pesannya", () => {
    render(<ToastContainer />);
    show("success", "Tersimpan");
    show("error", "Gagal menyimpan");
    show("info", "Sedang diproses");

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(3);
    expect(alerts[0]).toHaveTextContent("Tersimpan");
    expect(alerts[0].className).toContain("bg-green-50");
    expect(alerts[1]).toHaveTextContent("Gagal menyimpan");
    expect(alerts[1].className).toContain("bg-red-50");
    expect(alerts[2]).toHaveTextContent("Sedang diproses");
    expect(alerts[2].className).toContain("bg-primary-50");
    expect(screen.getByLabelText("Notifikasi")).toBeInTheDocument();
  });

  it("tombol tutup menghapus toast terkait saja", async () => {
    const user = userEvent.setup();
    render(<ToastContainer />);
    show("success", "Satu");
    show("success", "Dua");

    await user.click(screen.getAllByRole("button", { name: "Tutup notifikasi" })[0]);
    expect(screen.queryByText("Satu")).not.toBeInTheDocument();
    expect(screen.getByText("Dua")).toBeInTheDocument();
  });

  it("hilang otomatis: sukses 3 detik, info 4 detik, error 5 detik", () => {
    vi.useFakeTimers();
    render(<ToastContainer />);
    show("success", "S");
    show("info", "I");
    show("error", "E");

    act(() => void vi.advanceTimersByTime(2999));
    expect(screen.getAllByRole("alert")).toHaveLength(3);
    act(() => void vi.advanceTimersByTime(1));
    expect(screen.queryByText("S")).not.toBeInTheDocument();
    expect(screen.getByText("I")).toBeInTheDocument();

    act(() => void vi.advanceTimersByTime(1000));
    expect(screen.queryByText("I")).not.toBeInTheDocument();
    expect(screen.getByText("E")).toBeInTheDocument();

    act(() => void vi.advanceTimersByTime(1000));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("toast yang ditutup manual tidak memicu auto-dismiss kedua kali dan animasi masuk berjalan", async () => {
    vi.useFakeTimers();
    render(<ToastContainer />);
    show("success", "Halo");
    expect(screen.getByRole("alert").className).toContain("opacity-0");
    act(() => void vi.advanceTimersByTime(10));
    expect(screen.getByRole("alert").className).toContain("opacity-100");

    act(() => screen.getByRole("button", { name: "Tutup notifikasi" }).click());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    show("success", "Baru");
    act(() => void vi.advanceTimersByTime(3000)); // timer toast lama sudah dibersihkan
    expect(screen.queryByText("Baru")).not.toBeInTheDocument();
  });

  it("clearAll membersihkan semua toast", () => {
    render(<ToastContainer />);
    show("error", "A");
    show("error", "B");
    act(() => useToastStore.getState().clearAll());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
