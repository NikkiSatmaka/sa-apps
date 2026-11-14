import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, router } from "@/test";
import { HandoverModal } from "./HandoverModal";

describe("HandoverModal", () => {
  it("tampil sebagai alertdialog modal dengan judul, nama proyek, dan instruksi HLD", () => {
    renderWithProviders(<HandoverModal projectId="p-1" projectName="Migrasi Cloud" />, { role: "SA" });
    const dialog = screen.getByRole("alertdialog", { name: "Proyek Won!" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription(/High Level Design \(HLD\)/);
    expect(screen.getByText("Migrasi Cloud")).toBeInTheDocument();
  });

  it("hanya punya satu tombol aksi (tanpa close) dan fokus awal ada di sana", () => {
    renderWithProviders(<HandoverModal projectId="p-1" projectName="X" />, { role: "SA" });
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent("Buat HLD");
    expect(buttons[0]).toHaveFocus();
  });

  it("klik 'Buat HLD' memanggil onAcknowledge lalu menavigasi ke halaman dokumen proyek", async () => {
    const onAcknowledge = vi.fn();
    const { user } = renderWithProviders(
      <HandoverModal projectId="p-1" projectName="X" onAcknowledge={onAcknowledge} />,
      { role: "SA" }
    );
    await user.click(screen.getByRole("button", { name: "Buat HLD" }));
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
    expect(router.push).toHaveBeenCalledWith("/projects/p-1/documents");
  });

  it("tetap menavigasi tanpa callback onAcknowledge", async () => {
    const { user } = renderWithProviders(<HandoverModal projectId="p-2" projectName="X" />, { role: "SA" });
    await user.click(screen.getByRole("button", { name: "Buat HLD" }));
    expect(router.push).toHaveBeenCalledWith("/projects/p-2/documents");
  });

  it("tidak bisa ditutup dengan Escape atau klik backdrop", async () => {
    const { user } = renderWithProviders(<HandoverModal projectId="p-1" projectName="X" />, { role: "SA" });
    await user.keyboard("{Escape}");
    await user.click(document.querySelector('[aria-hidden="true"].absolute') as HTMLElement);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });
});
