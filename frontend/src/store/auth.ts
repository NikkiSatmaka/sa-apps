import { create } from "zustand";

/**
 * Zustand store untuk state autentikasi
 *
 * Menyimpan informasi user yang sedang login dan status autentikasi.
 * Token disimpan secara terpisah (httpOnly cookie / localStorage) — store ini
 * hanya menyimpan state yang dibutuhkan untuk rendering UI.
 */

// Tipe user sesuai dengan backend User model
interface User {
  id: string;
  email: string;
  full_name: string;
  role: "SA" | "Lead_SA" | "Sales" | "Product";
  /** Flag kemampuan admin yang menempel pada role fungsional (ADR 0012). */
  is_admin: boolean;
  avatar_url?: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User) => void;
  clearUser: () => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  setUser: (user) => set({ user, isAuthenticated: true, isLoading: false }),
  clearUser: () => set({ user: null, isAuthenticated: false, isLoading: false }),
  setLoading: (isLoading) => set({ isLoading }),
}));
