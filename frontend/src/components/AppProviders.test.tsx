import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { setOnline } from "@/test";
import { useToastStore } from "@/store/toast";
import AppProviders, { AppProviders as Named } from "./AppProviders";

describe("AppProviders", () => {
  it("merender children beserta ToastContainer dan OfflineIndicator", () => {
    render(
      <AppProviders>
        <p>Isi halaman</p>
      </AppProviders>,
    );
    expect(screen.getByText("Isi halaman")).toBeInTheDocument();

    act(() => useToastStore.getState().showToast("success", "Berhasil"));
    expect(screen.getByRole("alert")).toHaveTextContent("Berhasil");

    act(() => setOnline(false));
    expect(screen.getByRole("status")).toHaveTextContent("Anda sedang offline");
  });

  it("ekspor default dan bernama adalah komponen yang sama", () => {
    expect(AppProviders).toBe(Named);
  });

  it("memasang sinkronisasi offline: kembali online memicu pengiriman antrean", async () => {
    const { enqueueSubmission, getQueuedItems } = await import("@/lib/offline-queue");
    const { http, HttpResponse, api, server } = await import("@/test");
    let dikirim = 0;
    server.use(
      http.post(api("/projects"), () => {
        dikirim++;
        return HttpResponse.json({ status: "success", data: {}, message: "ok" }, { status: 201 });
      }),
    );
    setOnline(false, false);
    enqueueSubmission(api("/projects"), "POST", { project_name: "x" });
    render(<AppProviders>x</AppProviders>);

    await act(async () => {
      setOnline(true);
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(dikirim).toBe(1);
    expect(getQueuedItems()).toHaveLength(0);
  });
});
