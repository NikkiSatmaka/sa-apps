import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test";
import { DocumentForm } from "./DocumentForm";

describe("DocumentForm", () => {
  it("tidak menawarkan tipe Requirement (dibuat otomatis oleh sistem)", () => {
    renderWithProviders(<DocumentForm onSubmit={vi.fn()} />);
    const options = Array.from(
      (screen.getByLabelText(/Tipe Dokumen/) as HTMLSelectElement).options
    ).map((o) => o.value);
    expect(options).toEqual(["", "PropTek", "BOQ", "Mandays", "MoM", "RFP", "HLD"]);
    expect(options).not.toContain("Requirement");
  });

  it("menawarkan tiga folder tujuan", () => {
    renderWithProviders(<DocumentForm onSubmit={vi.fn()} />);
    const options = Array.from(
      (screen.getByLabelText(/Folder Tujuan/) as HTMLSelectElement).options
    ).map((o) => o.value);
    expect(options).toEqual(["", "Inventory", "Diagram", "Solutions"]);
  });

  it("submit kosong: menampilkan semua error wajib dan tidak memanggil onSubmit", async () => {
    const onSubmit = vi.fn();
    const { user } = renderWithProviders(<DocumentForm onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));

    expect(screen.getByText("Tipe dokumen wajib dipilih")).toBeInTheDocument();
    expect(screen.getByText("Link GDrive wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Folder tujuan wajib dipilih")).toBeInTheDocument();
    expect(screen.getByLabelText(/Tipe Dokumen/)).toBeInvalid();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("menolak link yang bukan http(s)", async () => {
    const onSubmit = vi.fn();
    const { user } = renderWithProviders(<DocumentForm onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByLabelText(/Tipe Dokumen/), "BOQ");
    await user.selectOptions(screen.getByLabelText(/Folder Tujuan/), "Solutions");
    await user.type(screen.getByLabelText(/Link Google Drive/), "ftp://server/file");
    await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));

    expect(screen.getByText("Link harus berupa URL yang valid")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("error pada field hilang saat pengguna mengubah field tersebut", async () => {
    const { user } = renderWithProviders(<DocumentForm onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));

    await user.selectOptions(screen.getByLabelText(/Tipe Dokumen/), "MoM");
    expect(screen.queryByText("Tipe dokumen wajib dipilih")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/Link Google Drive/), "h");
    expect(screen.queryByText("Link GDrive wajib diisi")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Folder Tujuan/), "Diagram");
    expect(screen.queryByText("Folder tujuan wajib dipilih")).not.toBeInTheDocument();
  });

  it("submit valid: mengirim data ter-trim, catatan dihilangkan bila kosong", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { user } = renderWithProviders(<DocumentForm onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByLabelText(/Tipe Dokumen/), "HLD");
    await user.selectOptions(screen.getByLabelText(/Folder Tujuan/), "Diagram");
    await user.type(screen.getByLabelText(/Link Google Drive/), "https://drive.google.com/x");
    await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));

    expect(onSubmit).toHaveBeenCalledWith({
      doc_type: "HLD",
      gdrive_link: "https://drive.google.com/x",
      folder_type: "Diagram",
    });
  });

  it("submit valid dengan catatan: catatan ter-trim ikut dikirim", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { user } = renderWithProviders(<DocumentForm onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByLabelText(/Tipe Dokumen/), "RFP");
    await user.selectOptions(screen.getByLabelText(/Folder Tujuan/), "Inventory");
    await user.type(screen.getByLabelText(/Link Google Drive/), "https://drive.google.com/x");
    await user.type(screen.getByLabelText(/Catatan/), "  versi final  ");
    await user.click(screen.getByRole("button", { name: "Simpan Dokumen" }));

    expect(onSubmit).toHaveBeenCalledWith({
      doc_type: "RFP",
      gdrive_link: "https://drive.google.com/x",
      folder_type: "Inventory",
      notes: "versi final",
    });
  });

  it("counter catatan dan batas 500 karakter", async () => {
    const { user } = renderWithProviders(<DocumentForm onSubmit={vi.fn()} />);
    const notes = screen.getByLabelText(/Catatan/);
    expect(screen.getByText("0/500")).toBeInTheDocument();
    await user.type(notes, "halo");
    expect(screen.getByText("4/500")).toBeInTheDocument();
    expect(notes).toHaveAttribute("maxlength", "500");
  });

  it("tombol Batal hanya ada bila onCancel diberikan", async () => {
    const onCancel = vi.fn();
    const { user, rerender } = renderWithProviders(<DocumentForm onSubmit={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(<DocumentForm onSubmit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Batal" })).not.toBeInTheDocument();
  });

  it("saat isSubmitting: semua kontrol dinonaktifkan dan tombol menampilkan Menyimpan...", () => {
    renderWithProviders(<DocumentForm onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting />);
    expect(screen.getByRole("button", { name: /Menyimpan/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
    expect(screen.getByLabelText(/Tipe Dokumen/)).toBeDisabled();
    expect(screen.getByLabelText(/Link Google Drive/)).toBeDisabled();
    expect(screen.getByLabelText(/Folder Tujuan/)).toBeDisabled();
    expect(screen.getByLabelText(/Catatan/)).toBeDisabled();
  });
});
