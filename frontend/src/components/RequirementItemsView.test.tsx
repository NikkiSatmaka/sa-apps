import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeRequirementDoc, makeRequirementItem } from "@/test/fixtures/requirement";
import { RequirementItemsView } from "./RequirementItemsView";

describe("RequirementItemsView", () => {
  it("menampilkan butir dikelompokkan per kategori sesuai urutan tetap", () => {
    const doc = makeRequirementDoc({
      content: [
        makeRequirementItem({ id: "a", kategori: "Asumsi", butir: "Jaringan tersedia" }),
        makeRequirementItem({ id: "b", kategori: "Teknis", butir: "Pakai PostgreSQL" }),
        makeRequirementItem({ id: "c", kategori: "Fungsional", butir: "Ekspor PDF" }),
        makeRequirementItem({ id: "d", kategori: "Fungsional", butir: "Login SSO" }),
      ],
    });
    render(<RequirementItemsView doc={doc} />);

    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Fungsional", "Teknis", "Asumsi"]);

    const fungsional = screen.getByRole("heading", { name: "Fungsional" }).closest("section")!;
    const butir = within(fungsional).getAllByRole("listitem").map((li) => li.textContent);
    expect(butir).toEqual(["Ekspor PDF", "Login SSO"]);
  });

  it("tidak menampilkan kategori tanpa butir", () => {
    render(<RequirementItemsView doc={makeRequirementDoc()} />);
    expect(screen.queryByRole("heading", { name: "Kepatuhan" })).not.toBeInTheDocument();
  });

  it("menampilkan pesan kosong saat content null atau tanpa butir", () => {
    const { rerender } = render(<RequirementItemsView doc={makeRequirementDoc({ content: null })} />);
    expect(screen.getByText("Belum ada butir.")).toBeInTheDocument();
    rerender(<RequirementItemsView doc={makeRequirementDoc({ content: [] })} />);
    expect(screen.getByText("Belum ada butir.")).toBeInTheDocument();
  });

  it("menampilkan peringatan teks terpotong hanya bila source_truncated", () => {
    const { rerender } = render(<RequirementItemsView doc={makeRequirementDoc({ source_truncated: true })} />);
    expect(screen.getByRole("status")).toHaveTextContent("Requirement dibuat dari teks yang terpotong");
    rerender(<RequirementItemsView doc={makeRequirementDoc({ source_truncated: false })} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("tidak menyediakan kontrol edit (read-only)", () => {
    render(<RequirementItemsView doc={makeRequirementDoc()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
