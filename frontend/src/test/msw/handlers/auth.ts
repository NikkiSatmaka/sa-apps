import { http, HttpResponse } from "msw";
import { backendUser, loginResponse, type Role } from "../../fixtures/users";
import { api } from "../base";

const ROLES: Role[] = ["Sales", "Product", "SA", "Lead_SA", "Admin"];

export const authHandlers = [
  http.get(api("/auth/config"), () => HttpResponse.json({ demo_mode: true })),
  http.post(api("/auth/demo-login"), async ({ request }) => {
    const { role } = (await request.json()) as { role: Role };
    if (!ROLES.includes(role)) {
      return HttpResponse.json({ status: "error", data: null, message: "Role tidak valid" }, { status: 422 });
    }
    return HttpResponse.json(loginResponse(role));
  }),
  http.post(api("/auth/refresh"), () => HttpResponse.json({ detail: "Refresh cookie tidak ditemukan." }, { status: 401 })),
  http.get(api("/auth/me"), ({ request }) => {
    const token = request.headers.get("Authorization")?.replace("Bearer ", "") ?? "";
    const role = token.startsWith("access-") ? (token.slice(7) as Role) : null;
    if (!role || !ROLES.includes(role)) {
      return HttpResponse.json({ status: "error", data: null, message: "Unauthorized" }, { status: 401 });
    }
    return HttpResponse.json(backendUser(role));
  }),
  http.post(api("/auth/logout"), () => HttpResponse.json({ status: "success", data: null, message: "Success" })),
];
