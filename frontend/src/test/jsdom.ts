/** Stub/polyfill jsdom untuk API browser yang tidak diimplementasi jsdom. */
import { vi } from "vitest";

/**
 * Ganti `window.location` dengan objek yang bisa diperiksa (jsdom tidak mengimplementasi
 * navigasi; menulis `location.href` hanya mencetak error "Not implemented").
 * Dipulihkan otomatis oleh `vi.unstubAllGlobals()` di setup.
 */
export function stubLocation(href = "http://localhost/") {
  const url = new URL(href);
  const loc = {
    href: url.href,
    origin: url.origin,
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
    assign: vi.fn(),
    replace: vi.fn(),
    reload: vi.fn(),
  };
  vi.stubGlobal("location", loc);
  return loc;
}

/** Atur `navigator.onLine` dan (opsional) kirim event `online`/`offline`. */
export function setOnline(online: boolean, dispatch = true) {
  Object.defineProperty(navigator, "onLine", { configurable: true, value: online });
  if (dispatch) window.dispatchEvent(new Event(online ? "online" : "offline"));
}
