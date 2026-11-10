import { describe, expect, it } from "vitest";
import { dynamic, GET } from "./route";

describe("GET /api/health", () => {
  it("menjawab 200 dengan {status: ok} tanpa memanggil backend", async () => {
    // Tanpa handler MSW: bila memanggil jaringan, request gagal (onUnhandledFrame: error).
    const res = GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });

  it("ditandai dinamis agar tidak di-cache saat build", () => {
    expect(dynamic).toBe("force-dynamic");
  });
});
