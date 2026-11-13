import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, errorEnvelope } from "@/test";
import { canOverrideBANT, OVERRIDE_ALLOWED_STATUSES, overrideBANT } from "./bant-override";

describe("canOverrideBANT", () => {
  it.each([
    { role: "Lead_SA" },
    { role: "SA", is_admin: true }, // admin = flag pada role fungsional (ADR 0012)
    { role: "Sales", is_admin: true },
  ])("%j boleh override pada status yang relevan", (user) => {
    for (const status of OVERRIDE_ALLOWED_STATUSES) expect(canOverrideBANT(user, status)).toBe(true);
  });

  it.each([
    { role: "Sales" },
    { role: "Product" },
    { role: "SA" },
    { role: "SA", is_admin: false },
    { role: "" },
    { role: undefined },
    null,
    undefined,
  ])("%j tidak boleh override", (user) => {
    expect(canOverrideBANT(user, "Need Clarification")).toBe(false);
  });

  it.each(["New", "Pending Assignment", "Scoring Pending", "Closed Win"])(
    "Lead_SA tidak boleh override pada status %s",
    (status) => {
      expect(canOverrideBANT({ role: "Lead_SA" }, status)).toBe(false);
    }
  );
});

describe("overrideBANT", () => {
  const scores = { budget: 20, authority: 15, need: 25, timeline: 10 };

  it("mengirim 4 sub-skor + alasan ke score-manual dan membuka envelope", async () => {
    let body: unknown;
    let url = "";
    server.use(
      http.post(api("/projects/:id/score-manual"), async ({ request }) => {
        body = await request.json();
        url = new URL(request.url).pathname;
        return HttpResponse.json({ status: "success", data: { total_score: 70, sub_scores: scores, status: "Pending Assignment" } });
      })
    );

    const result = await overrideBANT("p-1", scores, "Konfirmasi klien");

    expect(url).toMatch(/\/projects\/p-1\/score-manual$/);
    expect(body).toEqual({ ...scores, reason: "Konfirmasi klien" });
    expect(result).toMatchObject({ total_score: 70, status: "Pending Assignment" });
  });

  it("melempar ApiError berisi pesan backend saat ditolak", async () => {
    server.use(
      http.post(api("/projects/:id/score-manual"), () =>
        HttpResponse.json(errorEnvelope("Status tidak mengizinkan override"), { status: 409 })
      )
    );
    await expect(overrideBANT("p-1", scores, "x")).rejects.toMatchObject({
      status: 409,
      message: "Status tidak mengizinkan override",
    });
  });
});
