/** Seeding state auth per peran (Sales/SA/Lead_SA/Admin) untuk test. */
import { useAuthStore } from "@/store/auth";
import { users, type Role } from "./fixtures/users";

export type { Role };

/**
 * Isi store auth sebagai user dengan peran tertentu (sudah terautentikasi, tidak loading) dan
 * simpan token palsu di localStorage seperti hasil login sungguhan.
 */
export function seedAuth(role: Role, overrides: Partial<(typeof users)[Role]> = {}) {
  const user = { ...users[role], ...overrides };
  localStorage.setItem("access_token", `access-${role}`);
  localStorage.setItem("refresh_token", `refresh-${role}`);
  useAuthStore.getState().setUser(user);
  return user;
}

/** Kembalikan store ke keadaan awal modul (belum login, loading). */
export function resetAuthStore() {
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: true });
}
