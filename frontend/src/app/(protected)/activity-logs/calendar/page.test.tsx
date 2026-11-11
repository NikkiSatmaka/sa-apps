import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HttpResponse, api, errorEnvelope, http, renderWithProviders, server, successEnvelope } from "@/test";
import { GCAL_EVENTS_URL } from "@/test/msw/handlers/operations";
import { makeProject } from "@/test/fixtures/projects";
import CalendarSyncPage from "./page";

async function openMappingModal(user: ReturnType<typeof renderWithProviders>["user"]) {
  localStorage.setItem("google_calendar_token", "gtoken");
  const today = new Date();
  const iso = (d: Date, h: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), h).toISOString();
  server.use(
    http.get(GCAL_EVENTS_URL, () =>
      HttpResponse.json({ items: [{ id: "e1", summary: "Rapat", start: { dateTime: iso(today, 9) }, end: { dateTime: iso(today, 10) } }] })
    )
  );
  await user.click(screen.getByRole("button", { name: "Sync Calendar" }));
  await user.click(await screen.findByRole("button", { name: "Map ke Subtask" }));
}

describe("CalendarSyncPage", () => {
  it("menampilkan skeleton saat proyek dimuat, lalu panel Calendar Sync", async () => {
    const { container } = renderWithProviders(<CalendarSyncPage />, { role: "SA" });
    expect(screen.getByRole("heading", { name: "Calendar Sync" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Sync Calendar" })).not.toBeInTheDocument();

    expect(await screen.findByRole("button", { name: "Sync Calendar" })).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
  });

  it("memiliki tautan kembali ke Activity Log", async () => {
    renderWithProviders(<CalendarSyncPage />, { role: "SA" });
    expect(screen.getByRole("link", { name: "← Activity Log" })).toHaveAttribute("href", "/activity-logs");
    await screen.findByRole("button", { name: "Sync Calendar" });
  });

  it("meneruskan daftar proyek ke modal mapping (id_project dinormalisasi ke id)", async () => {
    server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope([makeProject({ id_project: "p-9", project_name: "Proyek Sembilan" })]))));
    const { user } = renderWithProviders(<CalendarSyncPage />, { role: "SA" });
    await screen.findByRole("button", { name: "Sync Calendar" });
    await openMappingModal(user);
    const option = screen.getByRole("option", { name: "Proyek Sembilan" }) as HTMLOptionElement;
    expect(option.value).toBe("p-9");
    expect(screen.queryByText("Tidak ada proyek tersedia untuk di-mapping.")).not.toBeInTheDocument();
  });

  it("daftar proyek kosong: modal mapping memperingatkan tidak ada proyek", async () => {
    server.use(http.get(api("/projects"), () => HttpResponse.json(successEnvelope([]))));
    const { user } = renderWithProviders(<CalendarSyncPage />, { role: "SA" });
    await screen.findByRole("button", { name: "Sync Calendar" });
    await openMappingModal(user);
    expect(screen.getByText("Tidak ada proyek tersedia untuk di-mapping.")).toBeInTheDocument();
  });

  it("error memuat proyek: panel tetap tampil dengan daftar proyek kosong (perilaku nyata)", async () => {
    server.use(http.get(api("/projects"), () => HttpResponse.json(errorEnvelope("gagal"), { status: 500 })));
    const { user } = renderWithProviders(<CalendarSyncPage />, { role: "SA" });
    await screen.findByRole("button", { name: "Sync Calendar" });
    await openMappingModal(user);
    expect(screen.getByText("Tidak ada proyek tersedia untuk di-mapping.")).toBeInTheDocument();
  });
});
