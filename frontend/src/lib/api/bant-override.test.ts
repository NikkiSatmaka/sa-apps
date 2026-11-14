import { describe, expect, it } from "vitest";
import { http, HttpResponse, server, api, errorEnvelope } from "@/test";
import { canOverrideBANT, OVERRIDE_ALLOWED_STATES, overrideBANT } from "./bant-override";

describe("canOverrideBANT", () => {
  it.each([
    { role: "Lead_SA" },
    { role: "SA", is_admin: true }, // admin = flag pada role fungsional (ADR 0012)
    { role: "Sales", is_admin: true },
  ])("%j boleh override pada status yang relevan", (user) => {
    for (const state of OVERRIDE_ALLOWED_STATES) expect(canOverrideBANT(user, "Intake", state)).toBe(true);
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
    expect(canOverrideBANT(user, "Intake", "Need Clarification")).toBe(false);
  });

  it.each(["Scoring", "Qualified"])("Lead_SA tidak boleh override pada Intake dengan qualification_state %s", (state) => {
    expect(canOverrideBANT({ role: "Lead_SA" }, "Intake", state)).toBe(false);
  });

  it.each(["Awaiting Assignment", "Assigned", "Won", "Closed", "Lost", "On Hold"])(
    "Lead_SA tidak boleh override pada status %s walau qualification_state tersisa Need Clarification",
    (status) => {
      expect(canOverrideBANT({ role: "Lead_SA" }, status, "Need Clarification")).toBe(false);
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
        return HttpResponse.json({ status: "success", data: { total_score: 70, sub_scores: scores, status: "Awaiting Assignment" } });
      })
    );

    const result = await overrideBANT("p-1", scores, "Konfirmasi klien");

    expect(url).toMatch(/\/projects\/p-1\/score-manual$/);
    expect(body).toEqual({ ...scores, reason: "Konfirmasi klien" });
    expect(result).toMatchObject({ total_score: 70, status: "Awaiting Assignment" });
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
