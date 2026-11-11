import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { QualificationAnswers, QualificationErrors } from "@/lib/qualification";
import { makeOpportunitySchema } from "@/test/fixtures/opportunity";
import { QualificationForm } from "./QualificationForm";

const schema = makeOpportunitySchema();

function Harness({ errors = {}, disabled }: { errors?: QualificationErrors; disabled?: boolean }) {
  const [answers, setAnswers] = useState<QualificationAnswers>({});
  return (
    <QualificationForm
      schema={schema}
      answers={answers}
      errors={errors}
      disabled={disabled}
      onChange={(f, v) => setAnswers((p) => ({ ...p, [f]: v }))}
    />
  );
}

describe("QualificationForm", () => {
  it("merender grup dan pertanyaan dari skema, melewati grup tanpa pertanyaan dan field header", () => {
    render(<Harness />);
    expect(screen.getByRole("region", { name: "Budget" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Authority" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Kelompok Kosong" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Target submit/)).not.toBeInTheDocument();
  });

  it("menandai wajib vs opsional dan menampilkan hint serta petunjuk baris", () => {
    render(<Harness />);
    expect(screen.getByText("Anggaran bulanan (MRR)").parentElement).toHaveTextContent("*");
    expect(screen.getByText("Email PIC").parentElement).toHaveTextContent("(opsional)");
    expect(screen.getByText("Dalam juta rupiah")).toBeInTheDocument();
    expect(screen.getByText("Kontak pengambil keputusan")).toBeInTheDocument();
  });

  it("menyusun dua pertanyaan ber-row sama dalam satu baris", () => {
    render(<Harness />);
    const nama = screen.getByLabelText(/Nama PIC/);
    const email = screen.getByLabelText(/Email PIC/);
    expect(nama.parentElement?.parentElement).toBe(email.parentElement?.parentElement);
  });

  it("mengirim perubahan tiap tipe input ke parent dan mencerminkannya", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText(/Anggaran bulanan/), "50");
    expect(screen.getByLabelText(/Anggaran bulanan/)).toHaveValue(50);
    await user.selectOptions(screen.getByLabelText(/Status anggaran/), "Dalam proses");
    expect(screen.getByLabelText(/Status anggaran/)).toHaveValue("Dalam proses");
    await user.type(screen.getByLabelText(/Nama PIC/), "Budi");
    expect(screen.getByLabelText(/Nama PIC/)).toHaveValue("Budi");
    await user.type(screen.getByLabelText(/Email PIC/), "b@x.id");
    expect(screen.getByLabelText(/Email PIC/)).toHaveAttribute("type", "email");
    await user.type(screen.getByLabelText(/Kebutuhan teknis/), "abc");
    expect(screen.getByLabelText(/Kebutuhan teknis/)).toHaveValue("abc");
  });

  it("menampilkan penghitung karakter untuk teks panjang, tanpa hint ganda saat tidak ada", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByText("0 karakter — Jelaskan singkat")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Kebutuhan teknis/), "  abc ");
    expect(screen.getByText("3 karakter — Jelaskan singkat")).toBeInTheDocument();
  });

  it("menampilkan penghitung tanpa hint dan hint teks biasa", () => {
    const s = makeOpportunitySchema({
      questions: [
        { ...schema.questions[4], hint: null },
        { ...schema.questions[5], hint: "Boleh dikosongkan" },
      ],
    });
    render(<QualificationForm schema={s} answers={{}} errors={{}} onChange={vi.fn()} />);
    expect(screen.getByText("0 karakter")).toBeInTheDocument();
    expect(screen.getByText("Boleh dikosongkan")).toBeInTheDocument();
  });

  it("menampilkan pesan error per field dengan aria-invalid dan aria-describedby", () => {
    render(<Harness errors={{ budget_mrr: "Wajib diisi", pic_name: undefined }} />);
    const input = screen.getByLabelText(/Anggaran bulanan/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Wajib diisi");
    expect(input).toHaveAccessibleDescription(/Wajib diisi/);
    expect(screen.getByLabelText(/Nama PIC/)).toHaveAttribute("aria-invalid", "false");
    expect(within(screen.getByRole("region", { name: "Authority" })).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("menonaktifkan semua input saat disabled", () => {
    render(<Harness disabled />);
    for (const el of screen.getAllByRole("textbox")) expect(el).toBeDisabled();
    expect(screen.getByLabelText(/Status anggaran/)).toBeDisabled();
  });

  it("memakai pilihan kosong bila choices null", () => {
    const s = makeOpportunitySchema({
      questions: [{ ...schema.questions[1], choices: null }],
    });
    render(<QualificationForm schema={s} answers={{}} errors={{}} onChange={vi.fn()} />);
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });

  it("menampilkan satu pertanyaan per baris bila row hanya satu atau lebih dari tiga", () => {
    const base = schema.questions[2];
    const q = (n: string, row: string | null) => ({ ...base, name: n, label: n, row });
    const s = makeOpportunitySchema({
      questions: [q("a", "r"), q("b", "r"), q("c", "r"), q("d", "r")],
    });
    render(<QualificationForm schema={s} answers={{}} errors={{}} onChange={vi.fn()} />);
    expect(screen.getAllByRole("textbox")).toHaveLength(4);
  });
});
