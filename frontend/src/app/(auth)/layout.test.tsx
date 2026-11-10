import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AuthLayout from "./layout";

describe("layout (auth)", () => {
  it("hanya meneruskan konten tanpa sidebar, header, maupun landmark navigasi", () => {
    render(
      <AuthLayout>
        <p>Isi login</p>
      </AuthLayout>,
    );
    expect(screen.getByText("Isi login")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
  });
});
