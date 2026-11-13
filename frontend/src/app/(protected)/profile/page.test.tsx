import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse, api, renderWithProviders, seedAuth, server, stubLocation } from "@/test";
import { useAuthStore } from "@/store/auth";
import ProfilePage from "./page";

describe("ProfilePage", () => {
  it("menampilkan skeleton selama auth memuat", () => {
    const { container } = renderWithProviders(<ProfilePage />);
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Profil Saya" })).not.toBeInTheDocument();
  });

  it("menampilkan nama, email, dan peran pengguna (read-only) beserta catatan akun Google", () => {
    renderWithProviders(<ProfilePage />, { role: "Lead_SA" });
    expect(screen.getByRole("heading", { level: 1, name: "Profil Saya" })).toBeInTheDocument();
    const dl = screen.getByText("Nama").closest("dl")!;
    expect(dl).toHaveTextContent("Lead SA Demo");
    expect(dl).toHaveTextContent("lead@example.com");
    expect(dl).toHaveTextContent("Lead_SA");
    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.getByText(/masuk melalui Google/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("peran fungsional dan flag admin ditampilkan bersama", () => {
    renderWithProviders(<ProfilePage />, { role: "Admin" });
    const dl = screen.getByText("Nama").closest("dl")!;
    expect(dl).toHaveTextContent("SA · Admin");
  });

  it("Keluar membersihkan sesi, memanggil /auth/logout, dan mengarahkan ke /login", async () => {
    const loc = stubLocation();
    let called = false;
    server.use(
      http.post(api("/auth/logout"), () => {
        called = true;
        return HttpResponse.json({ status: "success", data: null, message: "ok" });
      }),
    );
    seedAuth("Sales");
    const { user } = renderWithProviders(<ProfilePage />);
    await user.click(screen.getByRole("button", { name: "Keluar" }));
    await waitFor(() => expect(loc.href).toContain("/login"));
    expect(called).toBe(true);
    expect(useAuthStore.getState().user).toBeNull();
  });
});
