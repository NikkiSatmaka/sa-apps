import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Recommendation } from "@/lib/api/handover";
import { api, errorEnvelope, http, HttpResponse, renderWithProviders, server, successEnvelope } from "@/test";
import { RAGPanel } from "./RAGPanel";

function rec(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id_project: "p-1",
    project_name: "Proyek Lama",
    doc_type: "HLD",
    use_case_tags: ["Cloud Migration", "Security"],
    gdrive_link: "https://drive.google.com/file/d/xyz",
    match_count: 2,
    ...overrides,
  };
}

function useRecommendations(list: Recommendation[]) {
  server.use(http.get(api("/projects/:id/recommendations"), () => HttpResponse.json(successEnvelope(list))));
}

describe("RAGPanel", () => {
  it("proyek tanpa tags: pesan scoring belum selesai dan tidak ada permintaan jaringan", async () => {
    let called = false;
    server.use(
      http.get(api("/projects/:id/recommendations"), () => {
        called = true;
        return HttpResponse.json(successEnvelope([]));
      })
    );
    renderWithProviders(<RAGPanel projectId="p1" hasTags={false} />);
    expect(screen.getByRole("complementary", { name: "Panel Referensi Serupa" })).toBeInTheDocument();
    expect(screen.getByText("Rekomendasi akan tersedia setelah scoring selesai")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(called).toBe(false);
  });

  it("menampilkan skeleton saat memuat lalu daftar rekomendasi", async () => {
    useRecommendations([rec()]);
    renderWithProviders(<RAGPanel projectId="p1" />);
    expect(screen.getByLabelText("Memuat rekomendasi")).toHaveAttribute("aria-busy", "true");

    const link = await screen.findByRole("link", { name: "Buka dokumen HLD dari proyek Proyek Lama" });
    expect(link).toHaveAttribute("href", "https://drive.google.com/file/d/xyz");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Cloud Migration")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.queryByLabelText("Memuat rekomendasi")).not.toBeInTheDocument();
  });

  it("membatasi maksimal 5 rekomendasi dan membuang yang tanpa link Drive", async () => {
    const list = [
      ...Array.from({ length: 6 }, (_, i) =>
        rec({ id_project: `p-${i}`, project_name: `Proyek ${i}` })
      ),
    ];
    list.unshift(rec({ id_project: "x", project_name: "Tanpa Link", gdrive_link: null }));
    useRecommendations(list);
    renderWithProviders(<RAGPanel projectId="p1" />);

    await screen.findByRole("list", { name: "Daftar rekomendasi dokumen" });
    expect(screen.getAllByRole("link")).toHaveLength(5);
    expect(screen.queryByText("Tanpa Link")).not.toBeInTheDocument();
    expect(screen.queryByText("Proyek 5")).not.toBeInTheDocument();
  });

  it("rekomendasi tanpa tags tidak menampilkan badge", async () => {
    useRecommendations([rec({ use_case_tags: [] })]);
    renderWithProviders(<RAGPanel projectId="p1" />);
    await screen.findByRole("link");
    expect(screen.queryByText("Cloud Migration")).not.toBeInTheDocument();
  });

  it("daftar kosong: pesan belum ada referensi", async () => {
    useRecommendations([]);
    renderWithProviders(<RAGPanel projectId="p1" />);
    expect(await screen.findByText("Belum ada referensi serupa")).toBeInTheDocument();
  });

  it("error: menampilkan alert gagal memuat", async () => {
    server.use(
      http.get(api("/projects/:id/recommendations"), () =>
        HttpResponse.json(errorEnvelope("Server error"), { status: 500 })
      )
    );
    renderWithProviders(<RAGPanel projectId="p1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Gagal memuat rekomendasi.");
  });
});
