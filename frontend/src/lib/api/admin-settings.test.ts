import { describe, expect, it, vi } from "vitest";
import { getSettings, testConnection, updateSettings } from "./admin-settings";

const KEY = "sa_portal_admin_settings";

describe("getSettings", () => {
  it("tanpa data tersimpan: nilai default kosong dengan provider gemini", () => {
    const s = getSettings();
    expect(s.llmProvider.provider).toBe("gemini");
    expect(s.googleOAuth).toEqual({ clientId: "", clientSecret: "", redirectUri: "", allowedDomains: "" });
  });

  it("menggabungkan data tersimpan di atas default", () => {
    localStorage.setItem(KEY, JSON.stringify({ gmail: { credentials: "abc" } }));
    const s = getSettings();
    expect(s.gmail.credentials).toBe("abc");
    expect(s.googleDrive.serviceAccountKey).toBe("");
  });

  it("JSON rusak di storage → kembali ke default", () => {
    localStorage.setItem(KEY, "{bukan json");
    expect(getSettings().llmProvider.provider).toBe("gemini");
  });
});

describe("updateSettings", () => {
  it("menyimpan satu kategori setelah jeda 500 ms dan mempertahankan kategori lain", async () => {
    vi.useFakeTimers();
    localStorage.setItem(KEY, JSON.stringify({ gmail: { credentials: "lama" } }));

    const promise = updateSettings("googleDrive", { serviceAccountKey: "kunci" });
    await vi.advanceTimersByTimeAsync(499);
    expect(getSettings().googleDrive.serviceAccountKey).toBe(""); // belum tersimpan
    await vi.advanceTimersByTimeAsync(1);

    await expect(promise).resolves.toEqual({ success: true, message: "Settings berhasil disimpan" });
    const s = getSettings();
    expect(s.googleDrive.serviceAccountKey).toBe("kunci");
    expect(s.gmail.credentials).toBe("lama");
  });

  it("gagal menulis storage → success false", async () => {
    vi.useFakeTimers();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const promise = updateSettings("gmail", { credentials: "x" });
    await vi.advanceTimersByTimeAsync(500);
    await expect(promise).resolves.toEqual({ success: false, message: "Gagal menyimpan settings" });
  });
});

describe("testConnection (mock MVP)", () => {
  it("API key terisi → sukses setelah 1 detik dan menyebut provider", async () => {
    vi.useFakeTimers();
    const promise = testConnection("gemini", "kunci-rahasia");
    await vi.advanceTimersByTimeAsync(999);
    let selesai = false;
    void promise.then(() => (selesai = true));
    await Promise.resolve();
    expect(selesai).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(promise).resolves.toMatchObject({ success: true, message: expect.stringContaining("gemini") });
  });

  it.each(["", "   "])("API key kosong (%j) → gagal", async (key) => {
    vi.useFakeTimers();
    const promise = testConnection("openai", key);
    await vi.advanceTimersByTimeAsync(1000);
    await expect(promise).resolves.toEqual({ success: false, message: "API Key tidak boleh kosong" });
  });
});
