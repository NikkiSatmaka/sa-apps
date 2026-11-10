import { describe, expect, it } from "vitest";
import { useSidebarStore } from "./sidebar";

const store = () => useSidebarStore.getState();

describe("sidebar store", () => {
  it("awalnya terbuka", () => {
    expect(store().isOpen).toBe(true);
  });

  it("toggle membalik keadaan bolak-balik", () => {
    store().toggle();
    expect(store().isOpen).toBe(false);
    store().toggle();
    expect(store().isOpen).toBe(true);
  });

  it("close menutup dan idempoten", () => {
    store().close();
    store().close();
    expect(store().isOpen).toBe(false);
  });

  it("open membuka dan idempoten", () => {
    store().close();
    store().open();
    store().open();
    expect(store().isOpen).toBe(true);
  });
});
