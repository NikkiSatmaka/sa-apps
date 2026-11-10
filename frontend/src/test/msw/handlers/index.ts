/**
 * Handler default. Tiket lanjutan menambah handler di berkas grup masing-masing
 * (mis. `handlers/assignment.ts`) dan mendaftarkannya di sini — hindari mengedit berkas grup lain.
 */
import { authHandlers } from "./auth";
import { authPagesHandlers } from "./auth-pages";
import { documentHandlers } from "./documents";
import { libHandlers } from "./lib";
import { notificationHandlers } from "./notifications";
import { projectHandlers } from "./projects";
import { qualificationHandlers } from "./qualification";

export const handlers = [
  ...authHandlers,
  ...authPagesHandlers,
  ...projectHandlers,
  ...documentHandlers,
  ...qualificationHandlers,
  ...notificationHandlers,
  ...libHandlers,
];
