import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeSourceDoc } from "@/test/fixtures/project-detail";
import { SourceDocumentSection } from "./SourceDocumentSection";

describe("SourceDocumentSection", () => {
  it("tidak merender apa pun bila tidak ada dokumen", () => {
    const { container } = render(<SourceDocumentSection documents={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("tidak merender apa pun bila documents null (data belum ada)", () => {
    const { container } = render(<SourceDocumentSection documents={null as never} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["pending", "Sedang diekstrak"],
    ["extracted", "Terekstrak"],
    ["empty", "Tanpa teks"],
    ["failed", "Gagal diekstrak"],
  ] as const)("menampilkan status ekstraksi %s sebagai '%s'", (status, label) => {
    render(<SourceDocumentSection documents={[makeSourceDoc({ extraction_status: status })]} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("menampilkan jumlah karakter hanya untuk status terekstrak", () => {
    render(
      <SourceDocumentSection
        documents={[
          makeSourceDoc({ id: "a", filename: "a.pdf", text_length: 1234 }),
          makeSourceDoc({ id: "b", filename: "b.pdf", extraction_status: "failed", text_length: 99 }),
        ]}
      />,
    );
    const [a, b] = screen.getAllByRole("listitem");
    expect(a).toHaveTextContent("karakter");
    expect(b).not.toHaveTextContent("karakter");
  });

  it("memformat ukuran file B / KB / MB", () => {
    render(
      <SourceDocumentSection
        documents={[
          makeSourceDoc({ id: "1", filename: "kecil.pdf", size_bytes: 512 }),
          makeSourceDoc({ id: "2", filename: "sedang.pdf", size_bytes: 2048 }),
          makeSourceDoc({ id: "3", filename: "besar.pdf", size_bytes: 3 * 1024 * 1024 }),
        ]}
      />,
    );
    const items = within(screen.getByRole("list", { name: "Daftar Source document" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("512 B");
    expect(items[1]).toHaveTextContent("2.0 KB");
    expect(items[2]).toHaveTextContent("3.0 MB");
  });

  it("menandai dokumen terpotong dan menampilkan tipe dokumen", () => {
    render(<SourceDocumentSection documents={[makeSourceDoc({ truncated: true, doc_type: "RFP", filename: "rfp.pdf" })]} />);
    expect(screen.getByText("Terpotong")).toBeInTheDocument();
    expect(screen.getByText(/RFP ·/)).toBeInTheDocument();
  });

  it("tidak menampilkan badge Terpotong bila lengkap", () => {
    render(<SourceDocumentSection documents={[makeSourceDoc()]} />);
    expect(screen.queryByText("Terpotong")).not.toBeInTheDocument();
  });
});
