import { describe, expect, it } from "vitest";
import { useAuthStore } from "./auth";

const store = () => useAuthStore.getState();
const sa = { id: "u1", email: "sa@example.com", full_name: "Sa Satu", role: "SA" as const };

describe("auth store", () => {
  it("awalnya belum login dan masih memuat", () => {
    expect(store()).toMatchObject({ user: null, isAuthenticated: false, isLoading: true });
  });

  it("setUser menandai terautentikasi dan selesai memuat", () => {
    store().setUser(sa);
    expect(store()).toMatchObject({ user: sa, isAuthenticated: true, isLoading: false });
  });

  it("setUser berikutnya menggantikan user (mis. ganti peran)", () => {
    store().setUser(sa);
    store().setUser({ ...sa, id: "u2", role: "Lead_SA" });
    expect(store().user?.role).toBe("Lead_SA");
  });

  it("clearUser mengosongkan sesi tetapi tidak lagi memuat", () => {
    store().setUser(sa);
    store().clearUser();
    expect(store()).toMatchObject({ user: null, isAuthenticated: false, isLoading: false });
  });

  it("setLoading hanya mengubah flag loading", () => {
    store().setUser(sa);
    store().setLoading(true);
    expect(store()).toMatchObject({ user: sa, isAuthenticated: true, isLoading: true });
    store().setLoading(false);
    expect(store().isLoading).toBe(false);
  });

  it("tidak mempersistensi state ke localStorage (token dikelola terpisah)", () => {
    store().setUser(sa);
    expect(localStorage.length).toBe(0);
  });
});
