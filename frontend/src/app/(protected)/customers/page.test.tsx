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
  it("shows create and rename failures and lets the user cancel editing", async () => {
    server.use(
      http.get("*/customers", () => HttpResponse.json(successEnvelope([{ id: "c1", name: "Acme" }]))),
      http.post("*/customers", () => HttpResponse.json({ detail: "Create failed" }, { status: 409 })),
      http.patch("*/customers/:id", () => HttpResponse.json({ detail: "Rename failed" }, { status: 409 })),
    );
    renderWithProviders(<CustomersPage />, { role: "Lead_SA" });
    const row = (await screen.findByText("Acme")).closest("li")!;

    fireEvent.click(within(row).getByRole("button", { name: "Ganti nama" }));
    fireEvent.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("textbox", { name: "Nama Customer Acme" })).toBeNull();

    fireEvent.click(within(row).getByRole("button", { name: "Ganti nama" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nama Customer Acme" }), {
      target: { value: "Acme Renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));
    expect(await screen.findByRole("alert")).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Nama Customer baru" }), {
      target: { value: "Gamma" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buat Customer" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).not.toBe(""));
  });

  it("shows load errors and the empty Customer state", async () => {
    server.use(
      http.get("*/customers", () => HttpResponse.json({ detail: "Unavailable" }, { status: 500 })),
    );
    const first = renderWithProviders(<CustomersPage />, { role: "Lead_SA" });
    expect(await screen.findByText("Gagal memuat Customer.")).toBeTruthy();
    first.unmount();

    server.use(
      http.get("*/customers", () => HttpResponse.json(successEnvelope([]))),
    );
    renderWithProviders(<CustomersPage />, { role: "Lead_SA" });
    expect(await screen.findByText("Tidak ada Customer.")).toBeTruthy();
  });
});
