/** Smoke test utilitas test bersama (render, seeding auth, mock router, MSW, jsdom stub). */
import { screen } from "@testing-library/react";
import useSWR from "swr";
import { describe, expect, it } from "vitest";
import { fetcher } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { useRouter } from "next/navigation";
import { HttpResponse, http, api, renderWithProviders, router, seedAuth, server, setOnline, setParams, stubLocation } from "@/test";

function Projects() {
  const { data, error } = useSWR<{ project_name: string }[]>("/projects", fetcher);
  if (error) return <p>galat: {error.message}</p>;
  return <ul>{data?.map((p) => <li key={p.project_name}>{p.project_name}</li>)}</ul>;
}

describe("utilitas test", () => {
  it.each(["Sales", "SA", "Lead_SA", "Admin"] as const)("seedAuth mengisi store untuk peran %s", (role) => {
    seedAuth(role);
    const { user, isAuthenticated, isLoading } = useAuthStore.getState();
    expect(user?.role).toBe(role);
    expect(isAuthenticated).toBe(true);
    expect(isLoading).toBe(false);
    expect(localStorage.getItem("access_token")).toBe(`access-${role}`);
  });

  it("renderWithProviders memakai handler MSW default", async () => {
    renderWithProviders(<Projects />, { role: "SA" });
    expect(await screen.findByText("Proyek Contoh")).toBeInTheDocument();
  });

  it("handler default bisa ditimpa per test", async () => {
    server.use(http.get(api("/projects"), () => HttpResponse.json({ status: "error", data: null, message: "Rusak" }, { status: 500 })));
    renderWithProviders(<Projects />);
    expect(await screen.findByText("galat: Rusak")).toBeInTheDocument();
  });

  it("cache SWR tidak bocor antar render (isolasi per test)", async () => {
    const { unmount } = renderWithProviders(<Projects />);
    await screen.findByText("Proyek Contoh");
    unmount();
    server.use(http.get(api("/projects"), () => HttpResponse.json({ data: [{ project_name: "Baru" }] })));
    renderWithProviders(<Projects />);
    expect(screen.queryByText("Proyek Contoh")).not.toBeInTheDocument();
    expect(await screen.findByText("Baru")).toBeInTheDocument();
  });

  it("mock next/navigation: router, params dapat diperiksa", () => {
    setParams({ id: "p1" });
    function C() {
      const r = useRouter();
      r.push("/x");
      return null;
    }
    renderWithProviders(<C />);
    expect(router.push).toHaveBeenCalledWith("/x");
  });

  it("stub jsdom: location dan onLine", () => {
    const loc = stubLocation();
    window.location.href = "/login";
    expect(loc.href).toBe("/login");
    setOnline(false);
    expect(navigator.onLine).toBe(false);
  });

  it("state di-reset antar test (auth & onLine & localStorage)", () => {
    expect(useAuthStore.getState().user).toBeNull();
    expect(navigator.onLine).toBe(true);
    expect(localStorage.length).toBe(0);
  });

  it("request tanpa handler gagal (onUnhandledFrame: error), bukan lolos diam-diam", async () => {
    const err = await fetch(api("/tidak-ada-handler")).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(String((err as Error).cause)).toMatch(/Cannot bypass a request/);
  });
});
