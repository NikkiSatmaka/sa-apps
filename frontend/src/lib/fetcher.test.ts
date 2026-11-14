import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server, api, stubLocation, successEnvelope, errorEnvelope } from "@/test";
import { ApiError, apiRequest, clearAccessToken, fetcher, setAccessToken, swrConfig } from "./fetcher";

beforeEach(() => clearAccessToken());

describe("fetcher (GET)", () => {
  it("mengawali endpoint dengan base URL dan membuka envelope `data`", async () => {
    server.use(http.get(api("/ping"), () => HttpResponse.json(successEnvelope({ ok: true }))));
    await expect(fetcher("/ping")).resolves.toEqual({ ok: true });
  });

  it("mengembalikan body utuh bila tidak ada field `data`", async () => {
    server.use(http.get(api("/raw"), () => HttpResponse.json({ items: [1] })));
    await expect(fetcher("/raw")).resolves.toEqual({ items: [1] });
  });

  it("memakai URL absolut apa adanya (tanpa prefix base)", async () => {
    server.use(http.get("http://other.test/x", () => HttpResponse.json(successEnvelope(1))));
    await expect(fetcher("http://other.test/x")).resolves.toBe(1);
  });

  it("menyertakan header Authorization Bearer bila token ada", async () => {
    setAccessToken("tok123");
    let auth: string | null = null;
    server.use(
      http.get(api("/who"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(null));
      })
    );
    await fetcher("/who");
    expect(auth).toBe("Bearer tok123");
  });

  it("tidak mengirim Authorization bila tidak ada token", async () => {
    let auth: string | null = "belum-diset";
    server.use(
      http.get(api("/who"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(null));
      })
    );
    await fetcher("/who");
    expect(auth).toBeNull();
  });

  it("refresh gagal: hapus token dan arahkan ke login dengan kode sesi berakhir", async () => {
    setAccessToken("a");
    const loc = stubLocation();
    server.use(
      http.get(api("/secure"), () => HttpResponse.json(errorEnvelope("x"), { status: 401 })),
      http.post(api("/auth/refresh"), () => HttpResponse.json({}, { status: 401 })),
    );

    await expect(fetcher("/secure")).rejects.toMatchObject({ name: "ApiError", status: 401, message: "Unauthorized" });
    clearAccessToken();
    expect(loc.href).toBe("/login?error=session_expired");
  });

  it("401: refresh sekali lalu ulangi request dengan access token memory baru", async () => {
    let secureCalls = 0;
    let refreshCalls = 0;
    server.use(
      http.post(api("/auth/refresh"), () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: "baru", expires_in: 900 });
      }),
      http.get(api("/secure"), ({ request }) => {
        secureCalls += 1;
        if (secureCalls === 1) return HttpResponse.json({}, { status: 401 });
        return request.headers.get("Authorization") === "Bearer baru"
          ? HttpResponse.json(successEnvelope({ ok: true }))
          : HttpResponse.json({}, { status: 401 });
      }),
    );

    await expect(fetcher("/secure")).resolves.toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(secureCalls).toBe(2);
    clearAccessToken();
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("error non-401: pakai message backend dan simpan data/status", async () => {
    const body = errorEnvelope("Proyek tidak ditemukan");
    server.use(http.get(api("/missing"), () => HttpResponse.json(body, { status: 404 })));

    const err = await fetcher("/missing").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 404, message: "Proyek tidak ditemukan", data: body });
  });

  it("error tanpa body JSON: pesan generik dengan status", async () => {
    server.use(http.get(api("/boom"), () => new HttpResponse("<html>", { status: 500 })));
    await expect(fetcher("/boom")).rejects.toMatchObject({
      status: 500,
      message: "Request gagal dengan status 500",
    });
  });
});

describe("apiRequest (mutasi)", () => {
  it("default POST dengan body JSON dan membuka envelope", async () => {
    let received: unknown;
    let method = "";
    server.use(
      http.post(api("/things"), async ({ request }) => {
        method = request.method;
        received = await request.json();
        return HttpResponse.json(successEnvelope({ id: 1 }));
      })
    );
    await expect(apiRequest("/things", { body: { a: 1 } })).resolves.toEqual({ id: 1 });
    expect(method).toBe("POST");
    expect(received).toEqual({ a: 1 });
  });

  it("mendukung method lain (PUT/DELETE)", async () => {
    server.use(http.delete(api("/things/1"), () => HttpResponse.json(successEnvelope(null))));
    // data null → `json.data ?? json` jatuh ke body utuh
    await expect(apiRequest("/things/1", { method: "DELETE" })).resolves.toMatchObject({ status: "success" });
  });

  it("401 TIDAK memicu logout otomatis (beda dengan fetcher), hanya ApiError", async () => {
    localStorage.setItem("access_token", "a");
    const loc = stubLocation();
    server.use(http.post(api("/things"), () => HttpResponse.json(errorEnvelope("Token kadaluarsa"), { status: 401 })));

    await expect(apiRequest("/things", { body: { a: 1 } })).rejects.toMatchObject({ status: 401, message: "Token kadaluarsa" });
    expect(localStorage.getItem("access_token")).toBe("a");
    expect(loc.href).toBe("http://localhost/");
  });
});

describe("swrConfig.onErrorRetry", () => {
  const retry = swrConfig.onErrorRetry;

  it.each([401, 403])("tidak retry untuk status %i", (status) => {
    const revalidate = vi.fn();
    vi.useFakeTimers();
    retry(new ApiError("x", status), "k", {}, revalidate, { retryCount: 0 });
    vi.runAllTimers();
    expect(revalidate).not.toHaveBeenCalled();
  });

  it("tidak retry setelah 3 percobaan", () => {
    const revalidate = vi.fn();
    vi.useFakeTimers();
    retry(new ApiError("x", 500), "k", {}, revalidate, { retryCount: 3 });
    vi.runAllTimers();
    expect(revalidate).not.toHaveBeenCalled();
  });

  it("retry dengan exponential backoff 1s, 2s, 4s", () => {
    vi.useFakeTimers();
    for (const [retryCount, delay] of [[0, 1000], [1, 2000], [2, 4000]] as const) {
      const revalidate = vi.fn();
      retry(new ApiError("x", 500), "k", {}, revalidate, { retryCount });
      vi.advanceTimersByTime(delay - 1);
      expect(revalidate).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(revalidate).toHaveBeenCalledWith({ retryCount });
    }
  });
});

describe("apiRequest: kasus tambahan", () => {
  it("memakai URL absolut apa adanya dan tidak mengirim body bila body kosong", async () => {
    let text = "x";
    server.use(
      http.post("http://other.test/hook", async ({ request }) => {
        text = await request.text();
        return HttpResponse.json(successEnvelope("ok"));
      })
    );
    await expect(apiRequest("http://other.test/hook")).resolves.toBe("ok");
    expect(text).toBe("");
  });

  it("menyertakan Bearer token", async () => {
    setAccessToken("tok");
    let auth: string | null = null;
    server.use(
      http.post(api("/things"), ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(successEnvelope(null));
      })
    );
    await apiRequest("/things", { body: { a: 1 } });
    expect(auth).toBe("Bearer tok");
  });

  it("error tanpa JSON: pesan generik dengan status", async () => {
    server.use(http.post(api("/things"), () => new HttpResponse("<html>", { status: 502 })));
    await expect(apiRequest("/things", { body: 1 })).rejects.toMatchObject({
      status: 502,
      message: "Request gagal dengan status 502",
    });
  });
});

describe("ApiError", () => {
  it("adalah Error bernama ApiError dengan status dan data", () => {
    const err = new ApiError("x", 418, { a: 1 });
    expect(err).toBeInstanceOf(Error);
    expect(err).toMatchObject({ name: "ApiError", message: "x", status: 418, data: { a: 1 } });
  });
});
