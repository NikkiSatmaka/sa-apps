/**
 * API client override skor BANT oleh Lead_SA/Admin (#30).
 * POST /projects/{id}/score-manual: 4 sub-skor (0-25) + alasan wajib.
 */

import { apiRequest } from "../fetcher";
import { isPrivileged, type Actor } from "../roles";
import type { BANTSubScores } from "./projects";

export interface BANTOverrideResult {
  total_score: number;
  sub_scores: BANTSubScores;
  status: string;
  feedback?: string | null;
}

/** Status proyek yang boleh dioverride (selaras dengan backend). */
export const OVERRIDE_ALLOWED_STATUSES = [
  "Need Clarification",
  "Manual Review Required",
] as const;

/** Tombol override hanya untuk Lead_SA/admin (is_admin) pada status yang relevan. */
export function canOverrideBANT(
  actor: Actor | undefined | null,
  status: string
): boolean {
  return (
    isPrivileged(actor) &&
    (OVERRIDE_ALLOWED_STATUSES as readonly string[]).includes(status)
  );
}

export async function overrideBANT(
  projectId: string,
  scores: BANTSubScores,
  reason: string
): Promise<BANTOverrideResult> {
  return apiRequest<BANTOverrideResult>(`/projects/${projectId}/score-manual`, {
    method: "POST",
    body: { ...scores, reason },
  });
}
