import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthGuard } from "@/components/AuthGuard";
import { useAuthStore } from "@/store/auth";
import { api, http, HttpResponse, renderWithProviders, router, seedAuth, server } from "@/test";
import { backendUser, type Role } from "@/test/fixtures/users";
import { clearAccessToken, setAccessToken } from "@/lib/fetcher";

const renderGuard = () =>
  renderWithProviders(
    <AuthGuard>
      <p>Konten rahasia</p>
    </AuthGuard>,
  );

const roles: Role[] = ["Sales", "Product", "SA", "Lead_SA"];

describe("AuthGuard", () => {
  it("tanpa token: mengalihkan ke /login dan tidak pernah menampilkan konten", async () => {
    renderGuard();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Konten rahasia")).not.toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("memuat: menampilkan 'Memuat...' selagi token divalidasi, lalu konten setelah /auth/me sukses", async () => {
    setAccessToken("access-SA");
    renderGuard();
    expect(screen.getByText("Memuat...")).toBeInTheDocument();
    expect(screen.queryByText("Konten rahasia")).not.toBeInTheDocument();

    expect(await screen.findByText("Konten rahasia")).toBeInTheDocument();
    expect(screen.queryByText("Memuat...")).not.toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("mengirim token sebagai Bearer ke /auth/me", async () => {
    let auth: string | null = null;
    server.use(
      http.get(api("/auth/me"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(backendUser("SA"));
      }),
    );
    setAccessToken("access-SA");
    renderGuard();
    await screen.findByText("Konten rahasia");
    expect(auth).toBe("Bearer access-SA");
  });

  it.each(roles)("peran %s: store terisi dari /auth/me (field name → full_name) dan konten tampil", async (role) => {
    setAccessToken(`access-${role}`);
    renderGuard();
    expect(await screen.findByText("Konten rahasia")).toBeInTheDocument();
    const { user, isAuthenticated, isLoading } = useAuthStore.getState();
    expect(isAuthenticated).toBe(true);
    expect(isLoading).toBe(false);
    expect(user).toMatchObject({
      role: backendUser(role).role,
      is_admin: backendUser(role).is_admin,
      email: backendUser(role).email,
      full_name: backendUser(role).name,
    });
  });

  it("DIVERGENSI: guard tidak mengecek peran — semua peran melihat konten yang sama, tidak ada pengalihan karena peran", async () => {
    // Tiket meminta "pengalihan saat peran tidak berhak", tetapi AuthGuard hanya memeriksa keberadaan
    // & validitas token. Otorisasi per peran, bila ada, dilakukan di halaman masing-masing.
    for (const role of roles) {
      setAccessToken(`access-${role}`);
      const { unmount } = renderGuard();
      expect(await screen.findByText("Konten rahasia")).toBeInTheDocument();
      unmount();
      useAuthStore.getState().clearUser();
    }
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("token ditolak backend (401): token dihapus dan dialihkan ke /login", async () => {
    setAccessToken("kedaluwarsa");
    server.use(http.post(api("/auth/refresh"), () => HttpResponse.json({ detail: "Refresh token sudah expired." }, { status: 401 })));
    renderGuard();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?error=session_expired"));
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(screen.queryByText("Konten rahasia")).not.toBeInTheDocument();
    expect(screen.queryByText("Memuat...")).not.toBeInTheDocument();
  });

  it("backend error 500 diperlakukan sama seperti token tidak valid", async () => {
    server.use(http.get(api("/auth/me"), () => HttpResponse.json({}, { status: 500 })));
    setAccessToken("access-SA");
    renderGuard();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("error jaringan: token dihapus dan dialihkan ke /login", async () => {
    server.use(http.get(api("/auth/me"), () => HttpResponse.error()));
    setAccessToken("access-SA");
    renderGuard();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(screen.queryByText("Konten rahasia")).not.toBeInTheDocument();
  });

  it("sudah terautentikasi di store: tidak memanggil /auth/me lagi", async () => {
    let calls = 0;
    server.use(
      http.get(api("/auth/me"), () => {
        calls += 1;
        return HttpResponse.json(backendUser("Admin"));
      }),
    );
    seedAuth("Admin");
    renderGuard();
    expect(await screen.findByText("Konten rahasia")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("store terautentikasi tetapi refresh cookie tidak tersedia: dialihkan tanpa pesan sesi berakhir", async () => {
    seedAuth("SA");
    localStorage.clear();
    clearAccessToken();
    renderGuard();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Konten rahasia")).not.toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});
