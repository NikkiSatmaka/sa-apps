/**
 * Mock `next/navigation` yang bisa dikontrol per test.
 *
 * `setup.ts` memasang `vi.mock("next/navigation")` yang membaca state di sini, sehingga
 * komponen/halaman cukup memanggil helper ini (mis. `setParams({ id: "p1" })`) lalu
 * memeriksa `router.push`/`router.replace`. State di-reset otomatis setelah tiap test.
 */
import { vi } from "vitest";

export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

const state = {
  params: {} as Record<string, string | string[]>,
  pathname: "/",
  searchParams: new URLSearchParams(),
};

export function setParams(params: Record<string, string | string[]>) {
  state.params = params;
}

export function setPathname(pathname: string) {
  state.pathname = pathname;
}

/** Terima string query ("a=1&b=2") atau objek biasa. */
export function setSearchParams(search: string | Record<string, string>) {
  state.searchParams = new URLSearchParams(search);
}

export function resetNavigation() {
  Object.values(router).forEach((fn) => fn.mockReset());
  state.params = {};
  state.pathname = "/";
  state.searchParams = new URLSearchParams();
}

/** Dipakai oleh factory `vi.mock("next/navigation")` di setup.ts. */
export const navigationMock = {
  useRouter: () => router,
  useParams: () => state.params,
  usePathname: () => state.pathname,
  useSearchParams: () => state.searchParams,
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
};
