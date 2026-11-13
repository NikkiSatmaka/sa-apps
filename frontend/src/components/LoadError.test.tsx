import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoadError } from "./LoadError";

describe("LoadError", () => {
  it("menampilkan pesan sebagai alert yang bisa dibaca pembaca layar", () => {
    render(<LoadError message="Gagal memuat daftar proyek." onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Gagal memuat daftar proyek.");
  });

  it("tombol 'Coba lagi' memanggil onRetry satu kali per klik", async () => {
    const onRetry = vi.fn();
    render(<LoadError message="Gagal." onRetry={onRetry} />);

    await userEvent.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("onRetry yang mengembalikan promise tidak menjadi unhandled rejection saat gagal", async () => {
    const onRetry = vi.fn().mockRejectedValue(new Error("masih gagal"));
    render(<LoadError message="Gagal." onRetry={onRetry} />);

    await userEvent.click(screen.getByRole("button", { name: "Coba lagi" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
