/** Seeding state auth per peran (Sales/SA/Lead_SA/Admin) untuk test. */
import { useAuthStore } from "@/store/auth";
import { users, type Role } from "./fixtures/users";
import { clearAccessToken, setAccessToken } from "@/lib/fetcher";

export type { Role };

/**
 * Isi store auth sebagai user dengan peran tertentu (sudah terautentikasi, tidak loading) dan
 * simpan access token palsu di memory seperti hasil login sungguhan.
 */
export function seedAuth(role: Role, overrides: Partial<(typeof users)[Role]> = {}) {
  const user = { ...users[role], ...overrides };
  setAccessToken(`access-${role}`);
  useAuthStore.getState().setUser(user);
  return user;
}

/** Kembalikan store ke keadaan awal modul (belum login, loading). */
export function resetAuthStore() {
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: true });
  clearAccessToken();
}
