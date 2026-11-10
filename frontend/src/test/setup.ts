import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { useSidebarStore } from "@/store/sidebar";
import { useToastStore } from "@/store/toast";
import { resetAuthStore } from "./auth";
import { navigationMock, resetNavigation } from "./navigation";
import { server } from "./msw/server";

// Pemasangan mock harus di setup agar berlaku global untuk semua test.
vi.mock("next/navigation", () => navigationMock);

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));

beforeEach(() => {
  // jsdom tidak mengimplementasi confirm; default: user menyetujui (timpa per test).
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup(); // globals=false → RTL tidak auto-cleanup
  server.resetHandlers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  resetNavigation();
  resetAuthStore();
  useToastStore.getState().clearAll(); // juga membersihkan timer modul-level
  useSidebarStore.setState({ isOpen: true });
});

afterAll(() => server.close());
