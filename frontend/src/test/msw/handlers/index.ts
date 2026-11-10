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

export const handlers = [
  ...authHandlers,
  ...authPagesHandlers,
  ...projectHandlers,
  ...projectDetailHandlers,
  ...documentHandlers,
  ...qualificationHandlers,
  ...notificationHandlers,
  ...libHandlers,
  ...opportunityHandlers,
  ...requirementHandlers,
  ...operationsHandlers,
];
