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

/** qualification_state yang boleh dioverride, hanya saat status Intake (selaras `QS_OVERRIDE_ALLOWED`). */
export const OVERRIDE_ALLOWED_STATES = ["Need Clarification", "Manual Review"] as const;

/** Tombol override hanya untuk Lead_SA/admin (is_admin) pada Intake dengan qualification_state yang relevan. */
export function canOverrideBANT(
  actor: Actor | undefined | null,
  status: string,
  qualificationState?: string | null
): boolean {
  return (
    isPrivileged(actor) &&
    status === "Intake" &&
    (OVERRIDE_ALLOWED_STATES as readonly string[]).includes(qualificationState ?? "")
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
