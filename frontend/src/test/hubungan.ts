/**
 * Menyiapkan hubungan persona test ke satu proyek (hak tulis per hubungan, #154).
 *
 * `pasangHubungan(role, hubungan)` memasang handler `GET /projects/:id` dan `/projects/:id/tim-sa`
 * sehingga persona `role` (id dari `users`) berhubungan sebagai `hubungan`; orang lain di proyek
 * itu memakai id berbeda. `tak_terkait` = tidak terkait sama sekali.
 */
import { http, HttpResponse } from "msw";
import { successEnvelope } from "./fixtures/envelope";
import { makeProjectDetail, makeSATambahan, makeTimSA } from "./fixtures/project-detail";
import { users, type Role } from "./fixtures/users";
import { api } from "./msw/base";
import { server } from "./msw/server";

export type Hubungan =
  | "sa_utama"
  | "sa_tambahan"
  | "sales_pic"
  | "product_pic"
  | "contributor"
  | "viewer"
  | "tak_terkait";

export const SEMUA_HUBUNGAN: Hubungan[] = [
  "sa_utama",
  "sa_tambahan",
  "sales_pic",
  "product_pic",
  "contributor",
  "viewer",
  "tak_terkait",
];

const ORANG_LAIN = {
  sales: { id: "orang-lain-sales", name: "Sales Lain", email: "sales.lain@example.com" },
  product: { id: "orang-lain-product", name: "Product Lain", email: "product.lain@example.com" },
  sa: { id: "orang-lain-sa", name: "SA Lain", email: "sa.lain@example.com" },
};

export function pasangHubungan(
  role: Role,
  hubungan: Hubungan,
  overrides: Record<string, unknown> = {},
) {
  const saya = users[role];
  const sebagaiOrang = { id: saya.id, name: saya.full_name, email: saya.email };

  const detail = makeProjectDetail({
    sales_pic: hubungan === "sales_pic" ? sebagaiOrang : ORANG_LAIN.sales,
    product_pic: hubungan === "product_pic" ? sebagaiOrang : ORANG_LAIN.product,
    assigned_sa: hubungan === "sa_utama" ? sebagaiOrang : ORANG_LAIN.sa,
    collaborators:
      hubungan === "contributor" || hubungan === "viewer"
        ? [
            {
              id: "c-saya",
              user_id: saya.id,
              user_name: saya.full_name,
              user_email: saya.email,
              user_role: saya.role,
              role: hubungan,
              added_by_name: "Lead",
              created_at: "2025-01-02T00:00:00Z",
            },
          ]
        : [],
    ...overrides,
  });
  const tim = makeTimSA({
    sa_utama: hubungan === "sa_utama" ? { ...sebagaiOrang } : { ...ORANG_LAIN.sa },
    sa_tambahan:
      hubungan === "sa_tambahan" ? [makeSATambahan({ id: saya.id, name: saya.full_name, email: saya.email })] : [],
  });

  server.use(
    http.get(api("/projects/:id"), () => HttpResponse.json(successEnvelope(detail))),
    http.get(api("/projects/:id/tim-sa"), () => HttpResponse.json(successEnvelope(tim))),
  );
  return detail;
}
