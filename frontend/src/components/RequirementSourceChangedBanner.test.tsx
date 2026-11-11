import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import { RequirementSourceChangedBanner } from "./RequirementSourceChangedBanner";

function track() {
  const calls: string[] = [];
  server.use(
    http.post(api("/projects/:id/requirement/regenerate"), ({ request }) => {
      calls.push(new URL(request.url).pathname);
      return HttpResponse.json(successEnvelope(null), { status: 202 });
    }),
    http.post(api("/projects/:id/requirement/keep-version"), ({ request }) => {
      calls.push(new URL(request.url).pathname);
      return HttpResponse.json(successEnvelope(null));
    })
  );
  return calls;
}

describe("RequirementSourceChangedBanner", () => {
  it("menampilkan peringatan sumber berubah dengan dua aksi", () => {
    renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Sumber Requirement");
    expect(screen.getByRole("alert")).toHaveTextContent("Isi Requirement belum diubah.");
    expect(screen.getByRole("button", { name: "Generate ulang (timpa edit saya)" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Pertahankan versi saya" })).toBeEnabled();
  });

  it("Generate ulang: memanggil endpoint regenerate (bukan keep-version) lalu onChanged", async () => {
    const calls = track();
    const onChanged = vi.fn();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Generate ulang (timpa edit saya)" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(calls).toEqual(["/api/v1/projects/p1/requirement/regenerate"]);
  });

  it("Pertahankan versi saya: memanggil keep-version (bukan regenerate) lalu onChanged", async () => {
    const calls = track();
    const onChanged = vi.fn();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(calls).toEqual(["/api/v1/projects/p1/requirement/keep-version"]);
  });

  it("selama aksi berjalan: label berganti dan kedua tombol nonaktif", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.post(api("/projects/:id/requirement/keep-version"), async () => {
        await gate;
        return HttpResponse.json(successEnvelope(null));
      })
    );
    const onChanged = vi.fn();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));

    expect(await screen.findByRole("button", { name: "Menyimpan..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate ulang (timpa edit saya)" })).toBeDisabled();
    release();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Pertahankan versi saya" })).toBeEnabled();
  });

  it("selama regenerate: label Memulai... pada tombol regenerate", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.post(api("/projects/:id/requirement/regenerate"), async () => {
        await gate;
        return HttpResponse.json(successEnvelope(null), { status: 202 });
      })
    );
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Generate ulang (timpa edit saya)" }));
    expect(await screen.findByRole("button", { name: "Memulai..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pertahankan versi saya" })).toBeDisabled();
    release();
  });

  it("aksi gagal: menampilkan pesan error dan tidak memanggil onChanged", async () => {
    server.use(
      http.post(api("/projects/:id/requirement/keep-version"), () =>
        HttpResponse.json({ detail: "Tidak berhak" }, { status: 403 })
      )
    );
    const onChanged = vi.fn();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));

    expect(await screen.findByText("Tidak berhak")).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Pertahankan versi saya" })).toBeEnabled();
  });

  it("error hilang saat aksi diulang dan berhasil", async () => {
    let attempt = 0;
    server.use(
      http.post(api("/projects/:id/requirement/keep-version"), () => {
        attempt += 1;
        return attempt === 1
          ? HttpResponse.json({ detail: "Sementara gagal" }, { status: 500 })
          : HttpResponse.json(successEnvelope(null));
      })
    );
    const onChanged = vi.fn();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));
    await screen.findByText("Sementara gagal");
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Sementara gagal")).not.toBeInTheDocument();
  });

  it("kegagalan bukan Error: memakai pesan bawaan", async () => {
    const onChanged = vi.fn(() => {
      throw "boom";
    });
    track();
    const { user } = renderWithProviders(<RequirementSourceChangedBanner projectId="p1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "Pertahankan versi saya" }));
    expect(await screen.findByText("Aksi gagal dijalankan.")).toBeInTheDocument();
  });
});
