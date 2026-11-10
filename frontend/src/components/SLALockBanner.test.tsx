import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SLALockBanner } from "./SLALockBanner";

describe("SLALockBanner", () => {
  it("menampilkan peringatan akses folder dikunci sebagai alert", () => {
    render(<SLALockBanner />);
    expect(screen.getByRole("alert")).toHaveTextContent("Akses Folder Solutions Dikunci");
    expect(screen.getByRole("alert")).toHaveTextContent("lebih dari 5 hari");
  });

  it("tanpa callback tidak menampilkan tombol Input DQ Number", () => {
    render(<SLALockBanner />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("memanggil onInputDQ saat tombol diklik", async () => {
    const onInputDQ = vi.fn();
    render(<SLALockBanner onInputDQ={onInputDQ} />);
    await userEvent.click(screen.getByRole("button", { name: "Input DQ Number untuk membuka akses folder" }));
    expect(onInputDQ).toHaveBeenCalledTimes(1);
  });
});
