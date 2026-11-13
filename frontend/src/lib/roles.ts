/**
 * Role fungsional tunggal + flag `is_admin` (ADR 0012). Admin BUKAN role: ia kemampuan yang
 * menempel pada satu role fungsional. Semua pengecekan hak di UI lewat helper ini, bukan
 * membandingkan string role langsung, agar aturannya selaras dengan backend
 * (`app/core/dependencies.py`: `adalah_privileged`, `PERAN_REQUESTER`, `boleh_membuat_proyek`).
 */

export const ROLES = ["Sales", "Product", "SA", "Lead_SA"] as const;

export type Role = (typeof ROLES)[number];

/** Bagian user yang dibutuhkan untuk menentukan hak (cocok dengan `User` di store auth). */
export interface Actor {
  role?: string | null;
  is_admin?: boolean | null;
}

type Maybe<T> = T | null | undefined;

/** True hanya bila flag `is_admin` bernilai true. */
export function isAdmin(actor: Maybe<Actor>): boolean {
  return actor?.is_admin === true;
}

/** Hak penuh atas semua proyek: Lead_SA atau pemilik flag admin. */
export function isPrivileged(actor: Maybe<Actor>): boolean {
  return actor?.role === "Lead_SA" || isAdmin(actor);
}

/** Pembuat dan pemantau project: Sales atau Product (setara; hanya beda tim). */
export function isRequester(actor: Maybe<Actor>): boolean {
  return actor?.role === "Sales" || actor?.role === "Product";
}

/** Requester yang bukan privileged: dikenai pembatasan khusus requester (mis. tanpa hak tulis log). */
export function isRequesterTerbatas(actor: Maybe<Actor>): boolean {
  return isRequester(actor) && !isPrivileged(actor);
}

/** Boleh membuat project: Sales, Product, Lead_SA, atau admin; SA tidak. */
export function bisaMembuatProyek(actor: Maybe<Actor>): boolean {
  return isRequester(actor) || isPrivileged(actor);
}

/** Label peran untuk tampilan: role fungsional, diikuti "· Admin" bila punya flag admin. */
export function labelPeran(actor: Maybe<Actor>): string {
  if (!actor?.role) return "—";
  return isAdmin(actor) ? `${actor.role} · Admin` : actor.role;
}
