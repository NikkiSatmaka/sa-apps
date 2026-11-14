import { inspect } from "node:util";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, server } from "@/test";
import { DELETE, GET, PATCH, POST, PUT } from "./route";

const BACKEND = "http://backend:8000/api/v1";
const FRONTEND = "http://localhost:3000";

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) });
const req = (url: string, init?: ConstructorParameters<typeof NextRequest>[1]) =>
  new NextRequest(`${FRONTEND}${url}`, init);

beforeEach(() => {
  // Proxy sangat berisik di console; sunyikan agar keluaran test bersih.
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("proxy /api/v1/[...path] — penerusan request", () => {
  it("meneruskan GET dengan path, query string, dan header Authorization; host diganti host backend", async () => {
    let seen: Request | undefined;
    server.use(
      http.get(`${BACKEND}/projects/p1/documents`, ({ request }) => {
        seen = request;
        return HttpResponse.json({ ok: true });
      }),
    );
    const res = await GET(
      req("/api/v1/projects/p1/documents?page=2&q=a%20b", {
        headers: { Authorization: "Bearer tok", "X-Custom": "1" },
      }),
      ctx("projects", "p1", "documents"),
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(new URL(seen!.url).search).toBe("?page=2&q=a+b");
    expect(seen!.headers.get("authorization")).toBe("Bearer tok");
    expect(seen!.headers.get("x-custom")).toBe("1");
    expect(seen!.headers.get("host")).toBe("backend:8000"); // bukan host frontend
  });

  it.each([
    ["POST", POST],
    ["PUT", PUT],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
  ] as const)("meneruskan method %s beserta body teks", async (method, handler) => {
    let got: { method: string; body: string; type: string | null } | undefined;
    server.use(
      http.all(`${BACKEND}/items/1`, async ({ request }) => {
        got = { method: request.method, body: await request.text(), type: request.headers.get("content-type") };
        return HttpResponse.json({ done: true }, { status: 201 });
      }),
    );
    const res = await handler(
      req("/api/v1/items/1", {
        method,
        body: JSON.stringify({ a: 1 }),
        headers: { "Content-Type": "application/json" },
      }),
      ctx("items", "1"),
    );
    expect(res.status).toBe(201);
    expect(got).toEqual({ method, body: '{"a":1}', type: "application/json" });
  });

  it("GET tidak mengirim body", async () => {
    let body: string | undefined;
    server.use(
      http.get(`${BACKEND}/ping`, async ({ request }) => {
        body = await request.text();
        return HttpResponse.text("pong");
      }),
    );
    const res = await GET(req("/api/v1/ping"), ctx("ping"));
    expect(await res.text()).toBe("pong");
    expect(body).toBe("");
  });
});

describe("proxy — penerusan response & error upstream", () => {
  it("meneruskan status error upstream (404/422/500) beserta body-nya apa adanya", async () => {
    server.use(
      http.get(`${BACKEND}/nope`, () => HttpResponse.json({ detail: "tidak ada" }, { status: 404 })),
      http.get(`${BACKEND}/boom`, () => HttpResponse.text("kacau", { status: 500, statusText: "Server Error" })),
    );
    const notFound = await GET(req("/api/v1/nope"), ctx("nope"));
    expect(notFound.status).toBe(404);
    expect(await notFound.json()).toEqual({ detail: "tidak ada" });

    const boom = await GET(req("/api/v1/boom"), ctx("boom"));
    expect(boom.status).toBe(500);
    expect(await boom.text()).toBe("kacau");
  });

  it("menyalin header response upstream (mis. Set-Cookie/X-*), membuang hop-by-hop", async () => {
    server.use(
      http.get(`${BACKEND}/h`, () =>
        HttpResponse.text("x", {
          headers: { "X-Request-Id": "abc", "Keep-Alive": "timeout=5", "Content-Type": "text/plain" },
        }),
      ),
    );
    const res = await GET(req("/api/v1/h"), ctx("h"));
    expect(res.headers.get("x-request-id")).toBe("abc");
    expect(res.headers.get("keep-alive")).toBeNull();
    expect(res.headers.get("content-type")).toBe("text/plain");
  });

  it("tidak mengikuti redirect upstream untuk path biasa (redirect: manual) dan meneruskannya ke klien", async () => {
    server.use(http.get(`${BACKEND}/moved`, () => new HttpResponse(null, { status: 302, headers: { Location: "/x" } })));
    const res = await GET(req("/api/v1/moved"), ctx("moved"));
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/x");
  });

  it("backend tidak tersedia → 502 JSON dengan pesan Indonesia", async () => {
    server.use(http.get(`${BACKEND}/down`, () => HttpResponse.error()));
    const res = await GET(req("/api/v1/down"), ctx("down"));
    expect(res.status).toBe(502);
    const json = await res.json();
    expect(json.status).toBe("error");
    expect(json.message).toMatch(/^Backend tidak tersedia: /);
  });
});

describe("proxy — auth/callback", () => {
  const user = { id: "u1", email: "a@b.co", name: "Ana Čé", role: "SA" };
  const tokens = { access_token: "AT.secret", refresh_token: "RT.secret", token_type: "bearer" };
  const callback = (query = "?code=abc") => GET(req(`/api/v1/auth/callback${query}`), ctx("auth", "callback"));

  it("sukses: menukar respons callback menjadi redirect dengan authorization code sekali pakai", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ handoff_code: "handoff-123" })));
    const res = await callback();
    expect(res.status).toBe(307);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.origin + loc.pathname).toBe(`${FRONTEND}/auth/callback`);
    expect(loc.searchParams.get("code")).toBe("handoff-123");
    expect(loc.hash).toBe("");
    expect(loc.href).not.toMatch(/AT\.secret|RT\.secret/);
  });

  it("tidak pernah menaruh token di header Location", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ user, tokens })));
    const res = await callback();
    expect(res.headers.get("location") ?? "").not.toMatch(/AT\.secret|RT\.secret/);
  });

  it("calendar flow: 3xx + Location backend diteruskan apa adanya", async () => {
    server.use(
      http.get(
        `${BACKEND}/auth/callback`,
        () => new HttpResponse(null, { status: 302, headers: { Location: "http://localhost:3000/#gcal_token=g" } }),
      ),
    );
    const res = await callback();
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/#gcal_token=g");
  });

  it("callback menolak Location yang memuat Google access token mentah", async () => {
    server.use(
      http.get(`${BACKEND}/auth/callback`, () => new HttpResponse(null, {
        status: 302,
        headers: { Location: "http://localhost:3000/activity-logs/calendar#gcal_token=SECRET" },
      })),
    );
    const res = await callback();
    expect(res.headers.get("location")).not.toContain("SECRET");
  });

  it("3xx tanpa Location jatuh ke cabang error → /login?error=auth_failed", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => new HttpResponse("{}", { status: 302 })));
    const res = await callback();
    expect(res.headers.get("location")).toBe(`${FRONTEND}/login?error=auth_failed`);
  });

  it("403 → /login?error=domain_not_allowed", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ detail: "x" }, { status: 403 })));
    const res = await callback();
    expect(res.headers.get("location")).toBe(`${FRONTEND}/login?error=domain_not_allowed`);
  });

  it("error lain dengan detail → /login?error=<detail>; tanpa JSON → auth_failed", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ detail: "invalid_state" }, { status: 400 })));
    expect((await callback()).headers.get("location")).toBe(`${FRONTEND}/login?error=invalid_state`);

    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.text("<html>", { status: 500 })));
    expect((await callback()).headers.get("location")).toBe(`${FRONTEND}/login?error=auth_failed`);

    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({}, { status: 401 })));
    expect((await callback()).headers.get("location")).toBe(`${FRONTEND}/login?error=auth_failed`);
  });

  it("200 tanpa tokens/user atau body bukan JSON → jatuh ke passthrough (tidak redirect)", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ hello: "world" })));
    const res = await callback();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ hello: "world" });

    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.text("bukan json")));
    const res2 = await callback();
    expect(res2.status).toBe(200);
    expect(await res2.text()).toBe("bukan json");
  });

  it("path lain bernama mirip (auth/callback/x) diperlakukan sebagai proxy biasa", async () => {
    server.use(http.get(`${BACKEND}/auth/callback/x`, () => HttpResponse.json({ user, tokens })));
    const res = await GET(req("/api/v1/auth/callback/x"), ctx("auth", "callback", "x"));
    expect(res.status).toBe(200);
  });
});

describe("proxy — tidak membocorkan rahasia ke log server (#80)", () => {
  const user = { id: "u1", email: "a@b.co", name: "Ana", role: "SA" };

  /** Seluruh keluaran console proxy, dijadikan satu teks agar bisa dicari nilai rahasianya. */
  const keluaran = () =>
    (["log", "error", "warn", "info", "debug"] as const)
      .flatMap((k) => vi.mocked(console[k]).mock.calls)
      .map((args) => args.map((a) => (typeof a === "string" ? a : inspect(a, { depth: 5 }))).join(" "))
      .join("\n");

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "debug").mockImplementation(() => {});
  });

  const callback = (query = "?code=abc") => GET(req(`/api/v1/auth/callback${query}`), ctx("auth", "callback"));

  it("calendar flow: nilai gcal_token di header Location tidak ada di log, tetap diteruskan ke browser", async () => {
    server.use(
      http.get(
        `${BACKEND}/auth/callback`,
        () =>
          new HttpResponse(null, {
            status: 302,
            headers: { Location: "http://localhost:3000/#gcal_token=GCAL-RAHASIA-123" },
          }),
      ),
    );

    const res = await callback();

    expect(res.headers.get("location")).toContain("GCAL-RAHASIA-123");
    expect(keluaran()).not.toContain("GCAL-RAHASIA-123");
    expect(keluaran()).not.toContain("gcal_token");
  });

  it("login sukses: access/refresh token tidak ada di log atau Location", async () => {
    server.use(
      http.get(`${BACKEND}/auth/callback`, () =>
        HttpResponse.json({ user, tokens: { access_token: "AT-RAHASIA", refresh_token: "RT-RAHASIA" } }),
      ),
    );

    const res = await callback();

    expect(res.headers.get("location") ?? "").not.toMatch(/AT-RAHASIA|RT-RAHASIA/);
    expect(keluaran()).not.toMatch(/AT-RAHASIA|RT-RAHASIA/);
  });

  it("query string (kode OAuth sekali pakai, state) tidak dicetak; hanya path dan status", async () => {
    server.use(http.get(`${BACKEND}/auth/callback`, () => HttpResponse.json({ detail: "x" }, { status: 400 })));

    await callback("?code=KODE-OAUTH-RAHASIA&state=STATE-RAHASIA");

    expect(keluaran()).not.toMatch(/KODE-OAUTH-RAHASIA|STATE-RAHASIA/);
  });

  it("body 200 yang gagal di-parse: pesan galat JSON (memuat potongan body) tidak dicetak", async () => {
    server.use(
      http.get(`${BACKEND}/auth/callback`, () =>
        HttpResponse.text('{"tokens":{"access_token":"AT-BOCOR"} x'),
      ),
    );

    const res = await callback();

    expect(res.status).toBe(200);
    expect(keluaran()).not.toContain("AT-BOCOR");
    expect(keluaran()).toContain("auth/callback"); // galatnya tetap tercatat, hanya tanpa isi body
  });

  it("request biasa tetap dicatat: method, path, dan status (tanpa query string)", async () => {
    server.use(http.get(`${BACKEND}/projects`, () => HttpResponse.json({ ok: true })));

    await GET(req("/api/v1/projects?q=rahasia-pencarian"), ctx("projects"));

    const log = keluaran();
    expect(log).toContain("GET /api/v1/projects");
    expect(log).toContain("200");
    expect(log).not.toContain("rahasia-pencarian");
  });
});
