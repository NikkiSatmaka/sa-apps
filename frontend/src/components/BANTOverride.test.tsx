import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import { useToastStore } from "@/store/toast";
import { BANTOverride } from "./BANTOverride";

const SCORES = { budget: 10, authority: 12, need: 14, timeline: 16 };

function setup(props: Partial<Parameters<typeof BANTOverride>[0]> = {}) {
  return renderWithProviders(
    <BANTOverride projectId="p1" status="Need Clarification" actor={{ role: "Lead_SA" }} currentScores={SCORES} {...props} />,
  );
}

async function bukaForm(user: ReturnType<typeof setup>["user"]) {
  await user.click(screen.getByRole("button", { name: "Override skor BANT" }));
  return screen.getByRole("dialog", { name: "Override skor BANT" });
}

describe("BANTOverride — visibilitas", () => {
  const aktor = (role: string, is_admin = false) => ({ role, is_admin });

  it.each([
    ["Lead_SA", "Need Clarification"],
    ["Lead_SA", "Manual Review Required"],
    ["Admin", "Need Clarification"],
    ["Admin", "Manual Review Required"],
  ])("tombol muncul untuk %s pada status %s", (role, status) => {
    // "Admin" = SA dengan flag is_admin
    setup({ actor: role === "Admin" ? aktor("SA", true) : aktor(role), status });
    expect(screen.getByRole("button", { name: "Override skor BANT" })).toBeInTheDocument();
  });

  it.each([
    ["SA", "Need Clarification"],
    ["Sales", "Manual Review Required"],
    ["Product", "Need Clarification"],
    [undefined, "Need Clarification"],
    [null, "Need Clarification"],
    ["Lead_SA", "Assigned"],
    ["Admin", "Pending Assignment"],
    ["Lead_SA", "New"],
  ])("tombol TIDAK muncul untuk peran %s pada status %s", (role, status) => {
    const actor = role === "Admin" ? aktor("SA", true) : role ? aktor(role) : undefined;
    const { container } = setup({ actor, status });
    expect(container).toBeEmptyDOMElement();
  });
});

describe("BANTOverride — form", () => {
  it("mengisi sub-skor awal dari currentScores dan menampilkan total + hasil gate", async () => {
    const { user } = setup();
    const dialog = await bukaForm(user);
    expect(screen.getByLabelText(/Budget/)).toHaveValue(10);
    expect(screen.getByLabelText(/Authority/)).toHaveValue(12);
    expect(screen.getByLabelText(/Need/)).toHaveValue(14);
    expect(screen.getByLabelText(/Timeline/)).toHaveValue(16);
    expect(dialog).toHaveTextContent("Total: 52");
    expect(dialog).toHaveTextContent("→ Need Clarification");
  });

  it("memakai 0 bila currentScores kosong/nilai bukan angka", async () => {
    const { user } = setup({ currentScores: { budget: "x", note: "legacy" } });
    await bukaForm(user);
    for (const label of [/Budget/, /Authority/, /Need/, /Timeline/]) {
      expect(screen.getByLabelText(label)).toHaveValue(0);
    }
  });

  it("memakai 0 bila currentScores null", async () => {
    const { user } = setup({ currentScores: null });
    await bukaForm(user);
    expect(screen.getByLabelText(/Budget/)).toHaveValue(0);
  });

  it("total >= 60 menampilkan hasil Pending Assignment", async () => {
    const { user } = setup();
    const dialog = await bukaForm(user);
    await user.clear(screen.getByLabelText(/Budget/));
    await user.type(screen.getByLabelText(/Budget/), "18");
    expect(dialog).toHaveTextContent("Total: 60");
    expect(dialog).toHaveTextContent("→ Pending Assignment");
  });

  it("alasan wajib: tombol simpan nonaktif sampai alasan terisi (spasi saja tidak cukup)", async () => {
    const { user } = setup();
    await bukaForm(user);
    const simpan = screen.getByRole("button", { name: "Simpan override" });
    expect(simpan).toBeDisabled();
    await user.type(screen.getByLabelText(/Alasan override/), "   ");
    expect(simpan).toBeDisabled();
    await user.type(screen.getByLabelText(/Alasan override/), "Klarifikasi customer");
    expect(simpan).toBeEnabled();
  });

  it.each(["26", "-1", "1.5", ""])("sub-skor tidak valid (%j) menonaktifkan simpan dan menyembunyikan total", async (nilai) => {
    const { user } = setup();
    const dialog = await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "alasan");
    const budget = screen.getByLabelText(/Budget/);
    await user.clear(budget);
    if (nilai) await user.type(budget, nilai);
    expect(screen.getByRole("button", { name: "Simpan override" })).toBeDisabled();
    expect(dialog).toHaveTextContent("Total: —");
    expect(dialog).not.toHaveTextContent("→");
  });

  it("Batal menutup form tanpa request", async () => {
    const { user } = setup();
    await bukaForm(user);
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("submit lewat Enter pada form tanpa alasan tidak mengirim request", async () => {
    let dipanggil = false;
    server.use(http.post(api("/projects/p1/score-manual"), () => { dipanggil = true; return HttpResponse.json(successEnvelope({})); }));
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Budget/), "{Enter}");
    expect(dipanggil).toBe(false);
  });
});

describe("BANTOverride — submit", () => {
  it("sukses: mengirim 4 sub-skor + alasan (trim), menutup form, toast sukses", async () => {
    let body: unknown;
    server.use(
      http.post(api("/projects/p1/score-manual"), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(successEnvelope({ total_score: 70, sub_scores: SCORES, status: "Pending Assignment" }));
      }),
    );
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "  Sudah klarifikasi  ");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ ...SCORES, reason: "Sudah klarifikasi" });
    expect(useToastStore.getState().toasts).toEqual([
      expect.objectContaining({ type: "success", message: "Skor BANT dioverride: 70 (Pending Assignment)." }),
    ]);
  });

  it("sukses: form dibuka ulang dengan alasan kosong", async () => {
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "alasan");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await bukaForm(user);
    expect(screen.getByLabelText(/Alasan override/)).toHaveValue("");
  });

  it("penolakan server: pesan error ditampilkan, form tetap terbuka, tidak ada toast sukses", async () => {
    server.use(
      http.post(api("/projects/p1/score-manual"), () =>
        HttpResponse.json(errorEnvelope("Status proyek tidak boleh dioverride"), { status: 409 }),
      ),
    );
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "alasan");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Status proyek tidak boleh dioverride");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/Alasan override/)).toHaveValue("alasan");
    expect(screen.getByRole("button", { name: "Simpan override" })).toBeEnabled();
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("kegagalan jaringan menampilkan pesan error", async () => {
    server.use(http.post(api("/projects/p1/score-manual"), () => HttpResponse.error()));
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "alasan");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("saat menyimpan tombol menjadi 'Menyimpan...' dan nonaktif", async () => {
    let lepas!: () => void;
    const tunggu = new Promise<void>((r) => (lepas = r));
    server.use(
      http.post(api("/projects/p1/score-manual"), async () => {
        await tunggu;
        return HttpResponse.json(successEnvelope({ total_score: 70, sub_scores: SCORES, status: "Pending Assignment" }));
      }),
    );
    const { user } = setup();
    await bukaForm(user);
    await user.type(screen.getByLabelText(/Alasan override/), "alasan");
    await user.click(screen.getByRole("button", { name: "Simpan override" }));
    expect(await screen.findByRole("button", { name: "Menyimpan..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batal" })).toBeDisabled();
    lepas();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("klik backdrop menutup form", async () => {
    const { user, baseElement } = setup();
    await bukaForm(user);
    await user.click(baseElement.querySelector('[aria-hidden="true"]') as HTMLElement);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
