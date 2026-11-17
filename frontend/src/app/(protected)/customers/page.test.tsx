import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import CustomersPage from "./page";

afterEach(() => vi.restoreAllMocks());

describe("Customer management", () => {
  it.each(["Sales", "Product", "SA"] as const)("denies %s", (role) => {
    renderWithProviders(<CustomersPage />, { role });
    expect(screen.getByRole("alert").textContent).toContain("tidak memiliki akses");
    expect(screen.queryByRole("button", { name: "Buat Customer" })).toBeNull();
  });

  it.each(["Lead_SA", "Admin"] as const)("allows %s to search, create, and rename", async (role) => {
    let customers = [{ id: "c1", name: "Acme" }, { id: "c2", name: "Beta" }];
    server.use(
      http.get("*/customers", () => HttpResponse.json(successEnvelope(customers))),
      http.post("*/customers", async ({ request }) => {
        const body = await request.json() as { name: string };
        customers = [...customers, { id: "c3", name: body.name }];
        return HttpResponse.json(successEnvelope({ id: "c3", name: body.name }), { status: 201 });
      }),
      http.patch("*/customers/:id", async ({ request, params }) => {
        const body = await request.json() as { name: string };
        customers = customers.map((customer) => customer.id === params.id ? { ...customer, name: body.name } : customer);
        return HttpResponse.json(successEnvelope({ id: String(params.id), name: body.name }));
      }),
    );
    renderWithProviders(<CustomersPage />, { role });
    expect(await screen.findByText("Acme")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Cari Customer" }), { target: { value: "beta" } });
    expect(screen.getByText("Beta")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Cari Customer" }), { target: { value: "" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Nama Customer baru" }), { target: { value: "Gamma" } });
    fireEvent.click(screen.getByRole("button", { name: "Buat Customer" }));
    expect(await screen.findByText("Gamma")).toBeTruthy();
    const gammaRow = screen.getByText("Gamma").closest("li")!;
    fireEvent.click(within(gammaRow).getByRole("button", { name: "Ganti nama" }));
    const renameInput = screen.getByRole("textbox", { name: "Nama Customer Gamma" });
    fireEvent.change(renameInput, { target: { value: "Gamma Corp" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(screen.getByText("Gamma Corp")).toBeTruthy());
  });
});
