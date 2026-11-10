import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FileUpload, type FileItem } from "./FileUpload";

const PDF = "application/pdf";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function berkas(name: string, type: string, size = 1024) {
  return new File([new ArrayBuffer(size)], name, { type });
}

function Harness({ initial = [], disabled, spy }: { initial?: FileItem[]; disabled?: boolean; spy?: (f: FileItem[]) => void }) {
  const [files, setFiles] = useState<FileItem[]>(initial);
  return (
    <FileUpload
      files={files}
      disabled={disabled}
      onChange={(next) => {
        spy?.(next);
        setFiles(next);
      }}
    />
  );
}

const input = (c: HTMLElement) => c.querySelector('input[type="file"]') as HTMLInputElement;
const zona = () => screen.getByRole("button", { name: /Area upload file/ });

describe("FileUpload", () => {
  it("awalnya kosong: hanya zona upload dan aturan file", () => {
    render(<Harness />);
    expect(zona()).toBeInTheDocument();
    expect(screen.getByText(/PDF atau DOCX, maks 20MB per file, maks 5 file/)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("menerima PDF dan DOCX valid, menampilkan nama, ukuran, status, dan jumlah", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.upload(input(container), [berkas("a.pdf", PDF, 2048), berkas("b.docx", DOCX, 0)]);
    const list = screen.getByRole("list", { name: "Daftar file yang dipilih" });
    expect(list).toHaveTextContent("a.pdf");
    expect(list).toHaveTextContent("2.0 KB");
    expect(list).toHaveTextContent("0 B");
    expect(list).toHaveTextContent("PDF");
    expect(list).toHaveTextContent("DOC");
    expect(screen.getAllByText("✓ Valid")).toHaveLength(2);
    expect(screen.getByText("2 dari 5 file valid terpilih")).toBeInTheDocument();
  });

  it("menolak tipe selain PDF/DOCX dengan pesan error dan tanpa pemilih tipe", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container } = render(<Harness />);
    await user.upload(input(container), berkas("gambar.png", "image/png"));
    expect(screen.getByText(/Format tidak didukung\. Hanya PDF dan DOCX/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Tipe dokumen gambar.png")).not.toBeInTheDocument();
    expect(screen.getByText("0 dari 5 file valid terpilih")).toBeInTheDocument();
  });

  it("menolak file lebih dari 20MB dan menerima tepat 20MB", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.upload(input(container), [
      berkas("pas.pdf", PDF, 20 * 1024 * 1024),
      berkas("besar.pdf", PDF, 20 * 1024 * 1024 + 1),
    ]);
    expect(screen.getByText(/Ukuran file melebihi 20MB \(20\.0 MB\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Tipe dokumen pas.pdf")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tipe dokumen besar.pdf")).not.toBeInTheDocument();
  });

  it("membatasi maksimal 5 file dan menonaktifkan input saat penuh", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    const tujuh = Array.from({ length: 7 }, (_, i) => berkas(`f${i}.pdf`, PDF));
    await user.upload(input(container), tujuh);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByText("f5.pdf")).not.toBeInTheDocument();
    expect(input(container)).toBeDisabled();
    // drop saat penuh tidak menambah file
    fireEvent.drop(zona(), { dataTransfer: { files: [berkas("lagi.pdf", PDF)] } });
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });

  it("mengubah tipe Source document (MoM/RFP) per file", async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    const { container } = render(<Harness spy={spy} />);
    await user.upload(input(container), berkas("a.pdf", PDF));
    const pilih = screen.getByLabelText("Tipe dokumen a.pdf");
    expect(pilih).toHaveValue("");
    expect(pilih).toBeRequired();
    await user.selectOptions(pilih, "RFP");
    expect(pilih).toHaveValue("RFP");
    expect(spy.mock.lastCall![0][0].docType).toBe("RFP");
    await user.selectOptions(pilih, "MoM");
    expect(spy.mock.lastCall![0][0].docType).toBe("MoM");
  });

  it("menghapus file dari daftar", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.upload(input(container), [berkas("a.pdf", PDF), berkas("b.pdf", PDF)]);
    await user.click(screen.getByRole("button", { name: "Hapus file a.pdf" }));
    expect(screen.queryByText("a.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
  });

  it("menambah file ke daftar yang sudah ada tanpa menghilangkannya", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.upload(input(container), berkas("a.pdf", PDF));
    await user.upload(input(container), berkas("b.pdf", PDF));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("drag-and-drop: sorotan saat melayang, file ditambah saat drop, sorotan hilang saat keluar", () => {
    render(<Harness />);
    fireEvent.dragOver(zona());
    expect(screen.getByText("Lepaskan file disini")).toBeInTheDocument();
    fireEvent.dragLeave(zona());
    expect(screen.getByText(/Drag & drop file atau klik/)).toBeInTheDocument();
    fireEvent.dragOver(zona());
    fireEvent.drop(zona(), { dataTransfer: { files: [berkas("drop.pdf", PDF)] } });
    expect(screen.getByText("drop.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Drag & drop file atau klik/)).toBeInTheDocument();
  });

  it("drop tanpa file diabaikan", () => {
    render(<Harness />);
    fireEvent.drop(zona(), { dataTransfer: { files: [] } });
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("klik atau Enter/Spasi pada zona membuka pemilih file; tombol lain tidak", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    // Hitung event click yang sampai ke input (click() programatik dari zona).
    const klik = vi.fn();
    input(container).addEventListener("click", klik);
    await user.click(zona());
    expect(klik).toHaveBeenCalledTimes(1);
    zona().focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(klik).toHaveBeenCalledTimes(3);
    await user.keyboard("a");
    expect(klik).toHaveBeenCalledTimes(3);
  });

  it("saat disabled: tidak membuka pemilih, tidak menerima drop/hover, kontrol file dinonaktifkan", async () => {
    const user = userEvent.setup();
    const initial: FileItem[] = [{ file: berkas("a.pdf", PDF), id: "1", status: "valid", docType: "MoM" }];
    const { container } = render(<Harness disabled initial={initial} />);
    const klik = vi.fn();
    input(container).addEventListener("click", klik);
    await user.click(zona());
    expect(klik).not.toHaveBeenCalled();
    fireEvent.dragOver(zona());
    expect(screen.queryByText("Lepaskan file disini")).not.toBeInTheDocument();
    fireEvent.drop(zona(), { dataTransfer: { files: [berkas("b.pdf", PDF)] } });
    expect(screen.queryByText("b.pdf")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Tipe dokumen a.pdf")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hapus file a.pdf" })).toBeDisabled();
  });

  it("pemilihan file kosong (dibatalkan) tidak mengubah daftar", () => {
    const { container } = render(<Harness />);
    fireEvent.change(input(container), { target: { files: [] } });
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("menampilkan ukuran dalam MB", () => {
    const initial: FileItem[] = [{ file: berkas("m.pdf", PDF, 3 * 1024 * 1024), id: "1", status: "valid" }];
    render(<Harness initial={initial} />);
    expect(screen.getByText("3.0 MB")).toBeInTheDocument();
  });
});
