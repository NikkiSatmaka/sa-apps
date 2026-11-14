import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope, type Role } from "@/test";
import { makeUserSearchResult } from "@/test/fixtures/operations";
import { PeopleSection } from "./PeopleSection";

const POOL: Record<string, ReturnType<typeof makeUserSearchResult>[]> = {
  Product: [
    makeUserSearchResult({ id: "p1", name: "Produk Satu", email: "p1@x.com", role: "Product" }),
    makeUserSearchResult({ id: "p2", name: "Produk Dua", email: "p2@x.com", role: "Product" }),
  ],
  Sales: [
    makeUserSearchResult({ id: "s1", name: "Sales Satu", email: "s1@x.com", role: "Sales" }),
    makeUserSearchResult({ id: "s2", name: "Sales Dua", email: "s2@x.com", role: "Sales" }),
  ],
  Lead_SA: [
    makeUserSearchResult({ id: "l1", name: "Lead Satu", email: "l1@x.com", role: "Lead_SA" }),
    makeUserSearchResult({ id: "l2", name: "Lead Dua", email: "l2@x.com", role: "Lead_SA" }),
  ],
};

const PROJECT = {
  id_project: "PRJ-1",
  product_pic: { id: "p1", name: "Produk Satu", email: "p1@x.com" },
  sales_pic: { id: "s1", name: "Sales Satu", email: "s1@x.com" },
  lead_sa: { id: "l1", name: "Lead Satu", email: "l1@x.com" },
};

function serveSearch() {
  server.use(
    http.get(api("/projects/users/search"), ({ request }) => {
      const role = new URL(request.url).searchParams.get("role") ?? "";
      return HttpResponse.json(successEnvelope(POOL[role] ?? []));
    })
  );
}

function servePatch() {
  const diterima: { body: unknown } = { body: undefined };
  server.use(
    http.patch(api("/projects/PRJ-1/people"), async ({ request }) => {
      diterima.body = await request.json();
      return HttpResponse.json(successEnvelope({}));
    })
  );
  return diterima;
}

function setup(role: Role, project = PROJECT) {
  serveSearch();
  const onChanged = vi.fn();
  const utils = renderWithProviders(<PeopleSection project={project} onChanged={onChanged} />, { role });
  return { onChanged, ...utils };
}

describe("PeopleSection — hak akses", () => {
  it.each(["Sales", "Product", "SA"] as Role[])("%s tidak melihat tombol Ganti orang", (role) => {
    setup(role);
    expect(screen.queryByRole("button", { name: "Ganti orang" })).not.toBeInTheDocument();
  });

  it.each(["Lead_SA", "Admin"] as Role[])("%s melihat tombol Ganti orang", (role) => {
    setup(role);
    expect(screen.getByRole("button", { name: "Ganti orang" })).toBeInTheDocument();
  });
});

describe("PeopleSection — penggantian", () => {
  it("menampilkan tiga pilihan dengan nilai saat ini dan Product tanpa opsi kosong", async () => {
    const { user } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));

    expect(await screen.findByRole("option", { name: "Produk Dua" })).toBeInTheDocument();
    expect(screen.getByLabelText("Product Manager PIC")).toHaveValue("p1");
    expect(screen.getByLabelText("Sales PIC")).toHaveValue("s1");
    expect(screen.getByLabelText("Lead SA")).toHaveValue("l1");
    expect(screen.getByLabelText("Product Manager PIC").querySelector('option[value=""]')).toBeNull();
    expect(screen.getByRole("option", { name: "Tanpa Sales" })).toBeInTheDocument();
  });

  it("mengirim hanya field yang berubah lalu memanggil onChanged", async () => {
    const diterima = servePatch();
    const { user, onChanged } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await screen.findByRole("option", { name: "Produk Dua" });

    await user.selectOptions(screen.getByLabelText("Product Manager PIC"), "p2");
    await user.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(diterima.body).toEqual({ product_pic: "p2" });
    expect(screen.queryByLabelText("Product Manager PIC")).not.toBeInTheDocument();
  });

  it("memilih Tanpa Sales mengirim sales_pic null", async () => {
    const diterima = servePatch();
    const { user } = setup("Admin");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await screen.findByRole("option", { name: "Sales Dua" });

    await user.selectOptions(screen.getByLabelText("Sales PIC"), "");
    await user.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(diterima.body).toEqual({ sales_pic: null }));
  });

  it("mengganti Lead SA", async () => {
    const diterima = servePatch();
    const { user } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await screen.findByRole("option", { name: "Lead Dua" });

    await user.selectOptions(screen.getByLabelText("Lead SA"), "l2");
    await user.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(diterima.body).toEqual({ lead_sa: "l2" }));
  });

  it("Simpan nonaktif selama tidak ada perubahan", async () => {
    const { user } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await screen.findByRole("option", { name: "Produk Dua" });

    expect(screen.getByRole("button", { name: "Simpan" })).toBeDisabled();
  });

  it("orang saat ini tetap jadi pilihan walau tidak ada di hasil pencarian", async () => {
    const { user } = setup("Lead_SA", {
      ...PROJECT,
      lead_sa: { id: "l-diri", name: "Saya Sendiri", email: "me@x.com" },
    });
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));

    expect(await screen.findByRole("option", { name: "Saya Sendiri" })).toBeInTheDocument();
    expect(screen.getByLabelText("Lead SA")).toHaveValue("l-diri");
  });

  it("gagal menyimpan: menampilkan alert dan form tetap terbuka", async () => {
    server.use(
      http.patch(api("/projects/PRJ-1/people"), () =>
        HttpResponse.json(errorEnvelope("Hanya Lead_SA atau Admin."), { status: 403 })
      )
    );
    const { user, onChanged } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await screen.findByRole("option", { name: "Produk Dua" });
    await user.selectOptions(screen.getByLabelText("Product Manager PIC"), "p2");

    await user.click(screen.getByRole("button", { name: "Simpan" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Hanya Lead_SA atau Admin.");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Product Manager PIC")).toBeInTheDocument();
  });

  it("Batal menutup form tanpa mengirim apa pun", async () => {
    const diterima = servePatch();
    const { user } = setup("Lead_SA");
    await user.click(screen.getByRole("button", { name: "Ganti orang" }));
    await user.click(screen.getByRole("button", { name: "Batal" }));

    expect(screen.queryByLabelText("Product Manager PIC")).not.toBeInTheDocument();
    expect(diterima.body).toBeUndefined();
  });
});
