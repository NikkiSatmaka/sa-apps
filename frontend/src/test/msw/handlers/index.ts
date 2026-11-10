/**
 * Handler default. Tiket lanjutan menambah handler di berkas grup masing-masing
 * (mis. `handlers/assignment.ts`) dan mendaftarkannya di sini — hindari mengedit berkas grup lain.
 */
import { authHandlers } from "./auth";
import { authPagesHandlers } from "./auth-pages";
import { documentHandlers } from "./documents";
import { libHandlers } from "./lib";
import { notificationHandlers } from "./notifications";
import { opportunityHandlers } from "./opportunity";
import { projectDetailHandlers } from "./project-detail";
import { operationsHandlers } from "./operations";
import { projectHandlers } from "./projects";
import { qualificationHandlers } from "./qualification";
import { requirementHandlers } from "./requirement";
import { shellHandlers } from "./shell";

/**
 * URUTAN MENENTUKAN: MSW memakai handler pertama yang cocok. Aturan:
 * 1. Grup spesifik-fitur (shell, operations, requirement, ...) SEBELUM grup umum/default (`lib`).
 * 2. `operations` sebelum `shell` (untuk `/sa/available` yang dipakai modal assignment/reassign), keduanya
 *    sebelum grup ber-`/projects/:id`. `shell` memuat path statis (`/projects/status-summary`, `/projects/pending-assignment`)
 *    yang kalau tidak didahulukan tertangkap `/projects/:id` milik `project-detail`/`opportunity`.
 * Berkas test boleh menimpa lewat `server.use(...)`.
 */
export const handlers = [
  ...operationsHandlers,
  ...shellHandlers,
  ...requirementHandlers,
  ...authPagesHandlers,
  ...authHandlers,
  ...projectDetailHandlers,
  ...opportunityHandlers,
  ...projectHandlers,
  ...documentHandlers,
  ...qualificationHandlers,
  ...notificationHandlers,
  ...libHandlers,
];
