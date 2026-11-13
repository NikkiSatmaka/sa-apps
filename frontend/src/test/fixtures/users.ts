/**
 * Persona test. `Admin` BUKAN role (ADR 0012): ia SA dengan flag `is_admin`, sehingga skenario
 * "admin" membuktikan hak berbasis flag, bukan berbasis nilai role.
 */
export type Role = "SA" | "Lead_SA" | "Sales" | "Product" | "Admin";

/** Bentuk `User` store auth (frontend); id/email mengikuti akun demo backend. */
export interface FixtureUser {
  id: string;
  email: string;
  full_name: string;
  role: "SA" | "Lead_SA" | "Sales" | "Product";
  is_admin: boolean;
  avatar_url?: string;
}

export const users: Record<Role, FixtureUser> = {
  Sales: { id: "00000000-0000-4000-8000-000000000001", email: "sales@example.com", full_name: "Sales Demo", role: "Sales", is_admin: false },
  SA: { id: "00000000-0000-4000-8000-000000000002", email: "sa@example.com", full_name: "SA Demo", role: "SA", is_admin: false },
  Lead_SA: { id: "00000000-0000-4000-8000-000000000003", email: "lead@example.com", full_name: "Lead SA Demo", role: "Lead_SA", is_admin: false },
  Admin: { id: "00000000-0000-4000-8000-000000000004", email: "admin@example.com", full_name: "Admin Demo", role: "SA", is_admin: true },
  Product: { id: "00000000-0000-4000-8000-000000000005", email: "product@example.com", full_name: "Product Demo", role: "Product", is_admin: false },
};

/** Bentuk `UserResponse` backend (field `name`, bukan `full_name`) seperti pada /auth/me & demo-login. */
export function backendUser(role: Role) {
  const { full_name, ...rest } = users[role];
  return { ...rest, name: full_name, avatar_url: null };
}

/** Bentuk `LoginResponse` backend (/auth/demo-login): `{user, tokens}` tanpa envelope. */
export function loginResponse(role: Role) {
  return {
    user: backendUser(role),
    tokens: { access_token: `access-${role}`, refresh_token: `refresh-${role}`, token_type: "bearer" },
  };
}
