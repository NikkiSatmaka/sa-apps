import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, type Role } from "@/test";
import { DQNumberInput } from "./DQNumberInput";

function setup(role: Role, currentValue: string | null, extra: { isSubmitting?: boolean; onSubmit?: (v: string) => Promise<void> } = {}) {
  const onSubmit = extra.onSubmit ?? vi.fn().mockResolvedValue(undefined);
  const utils = renderWithProviders(
    <DQNumberInput currentValue={currentValue} onSubmit={onSubmit} isSubmitting={extra.isSubmitting} />,
    { role }
  );
  return { onSubmit, ...utils };
}

describe("DQNumberInput — belum ada DQ", () => {
  it("menampilkan form input dengan petunjuk dan tombol Simpan nonaktif saat kosong", () => {
    setup("SA", null);
    expect(screen.getByRole("form", { name: "Input DQ Number" })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Simpan DQ Number" })).toBeDisabled();
  });

  it("menampilkan penghitung karakter saat mengetik", async () => {
    const { user } = setup("SA", null);
    await user.type(screen.getByRole("textbox"), "DQ-1");
    expect(screen.getByText("4/20 karakter")).toBeInTheDocument();
  });

  it("validasi saat blur: terlalu pendek", async () => {
    const { user } = setup("SA", null);
    const input = screen.getByRole("textbox");
    await user.type(input, "DQ-1");
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("DQ Number minimal 5 karakter");
    expect(input).toBeInvalid();
  });

  it("validasi saat blur: karakter tidak valid", async () => {
    const { user } = setup("SA", null);
    await user.type(screen.getByRole("textbox"), "DQ 2024!");
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("Format DQ Number tidak valid");
  });

  it("validasi blur pada nilai kosong: wajib diisi", async () => {
    const { user } = setup("SA", null);
    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("DQ Number wajib diisi");
  });

  it("validasi real-time setelah touched, lalu menampilkan 'Format valid'", async () => {
    const { user } = setup("SA", null);
    const input = screen.getByRole("textbox");
    await user.type(input, "DQ");
    await user.tab();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await user.type(input, "-2024-001");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Format valid")).toBeInTheDocument();
  });

  it("input dibatasi maksimal 20 karakter", async () => {
    const { user } = setup("SA", null);
    const input = screen.getByRole("textbox");
    await user.type(input, "A".repeat(25));
    expect(input).toHaveValue("A".repeat(20));
  });

  it("submit valid memanggil onSubmit lalu mengosongkan field", async () => {
    const { user, onSubmit } = setup("SA", null);
    const input = screen.getByRole("textbox");
    await user.type(input, "DQ-2024-001");
    await user.click(screen.getByRole("button", { name: "Simpan DQ Number" }));
    expect(onSubmit).toHaveBeenCalledWith("DQ-2024-001");
    expect(input).toHaveValue("");
  });

  it("submit via Enter dengan nilai tidak valid menampilkan error tanpa memanggil onSubmit", async () => {
    const { user, onSubmit } = setup("SA", null);
    await user.type(screen.getByRole("textbox"), "ab{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("DQ Number minimal 5 karakter");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Enter pada nilai kosong/spasi tidak men-submit (tombol submit nonaktif memblokir implicit submission)", async () => {
    const { user, onSubmit } = setup("SA", null);
    await user.type(screen.getByRole("textbox"), "   {Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("saat isSubmitting input dan tombol nonaktif", () => {
    setup("SA", null, { isSubmitting: true });
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Simpan DQ Number" })).toBeDisabled();
  });
});

describe("DQNumberInput — DQ sudah diset, variasi per peran", () => {
  it("Sales: hanya baca, tanpa form edit", () => {
    setup("Sales", "DQ-2024-001");
    expect(screen.getByText("DQ-2024-001")).toBeInTheDocument();
    expect(screen.getByText("Tersimpan ✓")).toBeInTheDocument();
    expect(screen.getByText(/Hanya Lead SA yang dapat mengubahnya/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each<Role>(["Lead_SA", "Admin"])("%s: bisa mengubah DQ yang ada", async (role) => {
    const { user, onSubmit } = setup(role, "DQ-2024-001");
    expect(screen.getByText("DQ-2024-001")).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Masukkan DQ Number baru");
    expect(screen.getByRole("button", { name: "Simpan DQ Number baru" })).toBeDisabled();
    await user.type(input, "DQ-NEW-1");
    await user.click(screen.getByRole("button", { name: "Simpan DQ Number baru" }));
    expect(onSubmit).toHaveBeenCalledWith("DQ-NEW-1");
    expect(input).toHaveValue("");
  });

  it("Lead_SA: validasi saat mengubah DQ (error tampil dan tombol tidak mengirim)", async () => {
    const { user, onSubmit } = setup("Lead_SA", "DQ-2024-001");
    const input = screen.getByPlaceholderText("Masukkan DQ Number baru");
    await user.type(input, "ab");
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("DQ Number minimal 5 karakter");
    expect(input).toBeInvalid();
    await user.type(input, "{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    // koreksi -> error hilang (validasi real-time)
    await user.type(input, "cdef");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Lead_SA: form edit nonaktif saat isSubmitting", () => {
    setup("Lead_SA", "DQ-2024-001", { isSubmitting: true });
    expect(screen.getByPlaceholderText("Masukkan DQ Number baru")).toBeDisabled();
  });

  it("SA: DQ sudah diset tetapi tidak berhak edit → jatuh ke form input baru (perilaku nyata)", () => {
    // Komponen hanya membatasi Sales (read-only) dan Lead_SA/Admin (edit); SA mendapat form kosong.
    setup("SA", "DQ-2024-001");
    expect(screen.getByRole("form", { name: "Input DQ Number" })).toBeInTheDocument();
  });
});
