import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { api, http, HttpResponse, renderWithProviders, server, setParams, successEnvelope, type Role } from "@/test";
import { makeCollaborator } from "@/test/fixtures/operations";
import { DETAIL_ID, makeProjectDetail, makeSourceDoc, makeStoryItem } from "@/test/fixtures/project-detail";
import ProjectDetailPage from "./page";

/**
 * Pengguna tak terkait (#109, ADR 0011): baca terbuka. Detail, Story, Source Document, dan
 * kolaborator tetap dirender (anak nyata, tidak di-stub); hanya kontrol tulis yang disembunyikan.
 * Id pengguna persona tidak ada di orang mana pun pada proyek ini.
 */
const TAK_TERKAIT: Role[] = ["Sales", "Product", "SA"];

beforeEach(() => {
  setParams({ id: DETAIL_ID });
  server.use(
    http.get(api("/projects/:id"), () =>
      HttpResponse.json(
        successEnvelope(
          makeProjectDetail({
            source_documents: [makeSourceDoc({ filename: "notulen-rapat.pdf" })],
            collaborators: [makeCollaborator({ user_name: "Citra Dewi" })],
          }),
        ),
      ),
    ),
    http.get(api("/projects/:id/story"), () =>
      HttpResponse.json(
        successEnvelope({
          items: [makeStoryItem({ raw_notes: "Diskusi arsitektur tim" })],
          total: 1,
          page: 1,
          page_size: 5,
        }),
      ),
    ),
    http.get(api("/projects/:id/collaborators"), () =>
      HttpResponse.json(successEnvelope({ items: [makeCollaborator({ user_name: "Citra Dewi" })], total: 1 })),
    ),
  );
});

describe("Detail proyek — pengguna tak terkait tetap bisa membaca", () => {
  it.each(TAK_TERKAIT)("%s: detail, Source Document, Story, dan kolaborator dirender", async (role) => {
    renderWithProviders(<ProjectDetailPage />, { role });

    expect(await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" })).toBeInTheDocument();
    expect(await screen.findByText("notulen-rapat.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Citra Dewi")).toBeInTheDocument();
    expect(await screen.findByText(/Diskusi arsitektur tim/)).toBeInTheDocument();
  });

  // Tombol "Edit" tetap tampil untuk semua peran (backend yang menegakkan; hak tulis di luar #109).
  it.each(TAK_TERKAIT)("%s: tanpa kontrol privileged (Hapus, Ganti orang, Assign, Reassign)", async (role) => {
    renderWithProviders(<ProjectDetailPage />, { role });
    await screen.findByRole("heading", { level: 1, name: "Migrasi Cloud ACME" });

    expect(screen.queryByRole("button", { name: "Hapus" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ganti orang" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign SA" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reassign SA" })).not.toBeInTheDocument();
  });
});
