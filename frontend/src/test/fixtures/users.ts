export type Role = "SA" | "Lead_SA" | "Sales" | "Admin";

/** Bentuk `User` store auth (frontend); id/email mengikuti akun demo backend. */
export const users: Record<Role, { id: string; email: string; full_name: string; role: Role; avatar_url?: string }> = {
  Sales: { id: "00000000-0000-4000-8000-000000000001", email: "sales@example.com", full_name: "Sales Demo", role: "Sales" },
  SA: { id: "00000000-0000-4000-8000-000000000002", email: "sa@example.com", full_name: "SA Demo", role: "SA" },
  Lead_SA: { id: "00000000-0000-4000-8000-000000000003", email: "lead@example.com", full_name: "Lead SA Demo", role: "Lead_SA" },
  Admin: { id: "00000000-0000-4000-8000-000000000004", email: "admin@example.com", full_name: "Admin Demo", role: "Admin" },
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
