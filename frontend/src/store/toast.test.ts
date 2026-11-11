import { beforeEach, describe, expect, it, vi } from "vitest";
import { useToastStore } from "./toast";

const store = () => useToastStore.getState();

beforeEach(() => {
  vi.useFakeTimers();
});

describe("toast store", () => {
  it("menambah toast dengan tipe, pesan, dan id unik", () => {
    store().showToast("success", "Tersimpan");
    store().showToast("error", "Gagal");

    const [a, b] = store().toasts;
    expect(a).toMatchObject({ type: "success", message: "Tersimpan" });
    expect(b).toMatchObject({ type: "error", message: "Gagal" });
    expect(a.id).not.toBe(b.id);
  });

  it.each([
    ["success", 3000],
    ["error", 5000],
    ["info", 4000],
  ] as const)("toast %s hilang otomatis tepat setelah %i ms", (type, ms) => {
    store().showToast(type, "pesan");
    vi.advanceTimersByTime(ms - 1);
    expect(store().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(store().toasts).toHaveLength(0);
  });

  it("auto-dismiss hanya menghapus toast miliknya", () => {
    store().showToast("success", "pertama"); // 3000
    vi.advanceTimersByTime(1000);
    store().showToast("error", "kedua"); // hilang di 6000 total
    vi.advanceTimersByTime(2000); // 3000 total → pertama hilang
    expect(store().toasts.map((t) => t.message)).toEqual(["kedua"]);
  });

  it("dismissToast menghapus toast tertentu dan membatalkan timernya", () => {
    store().showToast("success", "a");
    store().showToast("success", "b");
    const [a] = store().toasts;
    store().dismissToast(a.id);
    expect(store().toasts.map((t) => t.message)).toEqual(["b"]);
    expect(vi.getTimerCount()).toBe(1); // timer a sudah dibersihkan
  });

  it("dismissToast untuk id tak dikenal tidak mengubah apa pun", () => {
    store().showToast("info", "a");
    store().dismissToast("tidak-ada");
    expect(store().toasts).toHaveLength(1);
  });

  it("clearAll mengosongkan toast dan membersihkan semua timer", () => {
    store().showToast("success", "a");
    store().showToast("error", "b");
    store().clearAll();
    expect(store().toasts).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });
});
