"use client";

import { useState } from "react";
import { mutate as globalMutate } from "swr";
import { canOverrideBANT, overrideBANT } from "@/lib/api/bant-override";
import type { BANTSubScores } from "@/lib/api/projects";
import { useToastStore } from "@/store/toast";
import type { Actor } from "@/lib/roles";

/**
 * Tombol + form "Override skor BANT" (#30).
 *
 * Tampil hanya untuk Lead_SA/Admin pada status Intake dengan qualification_state
 * Need Clarification / Manual Review. Empat sub-skor 0-25 dan alasan wajib.
 */

interface BANTOverrideProps {
  projectId: string;
  status: string;
  qualificationState?: string | null;
  /** Pengguna saat ini (role fungsional + flag admin). */
  actor: Actor | undefined | null;
  /** Boleh memuat field lain (mis. metadata legacy); hanya 4 sub-skor yang dipakai. */
  currentScores?: Record<string, unknown> | null;
}

const CRITERIA: { key: keyof BANTSubScores; label: string }[] = [
  { key: "budget", label: "Budget" },
  { key: "authority", label: "Authority" },
  { key: "need", label: "Need" },
  { key: "timeline", label: "Timeline" },
];

function initialScore(
  scores: Record<string, unknown> | null | undefined,
  key: keyof BANTSubScores
): string {
  const v = scores?.[key];
  return typeof v === "number" ? String(v) : "0";
}

export function BANTOverride({
  projectId,
  status,
  qualificationState,
  actor,
  currentScores,
}: BANTOverrideProps) {
  const [open, setOpen] = useState(false);
  const [scores, setScores] = useState<Record<keyof BANTSubScores, string>>({
    budget: initialScore(currentScores, "budget"),
    authority: initialScore(currentScores, "authority"),
    need: initialScore(currentScores, "need"),
    timeline: initialScore(currentScores, "timeline"),
  });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const showToast = useToastStore((s) => s.showToast);

  if (!canOverrideBANT(actor, status, qualificationState)) return null;

  const parsed = CRITERIA.map(({ key }) => ({ key, n: Number(scores[key]) }));
  const invalid = parsed.some(
    ({ n }, i) => scores[CRITERIA[i].key].trim() === "" || !Number.isInteger(n) || n < 0 || n > 25
  );
  const total = parsed.reduce((sum, { n }) => sum + (Number.isFinite(n) ? n : 0), 0);
  const canSubmit = !invalid && reason.trim().length > 0 && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload = Object.fromEntries(
        parsed.map(({ key, n }) => [key, n])
      ) as unknown as BANTSubScores;
      const res = await overrideBANT(projectId, payload, reason.trim());
      showToast("success", `Skor BANT dioverride: ${res.total_score} (${res.status}).`);
      setOpen(false);
      setReason("");
      await globalMutate(`/projects/${projectId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal melakukan override skor BANT");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="px-3 py-1.5 text-sm font-medium text-purple-700 border border-purple-300
                   rounded-lg hover:bg-purple-50 transition-colors min-h-[36px]"
      >
        Override skor BANT
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <form
            onSubmit={handleSubmit}
            role="dialog"
            aria-label="Override skor BANT"
            className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-5 space-y-4"
          >
            <h2 className="text-lg font-semibold text-neutral-900">Override skor BANT</h2>
            <p className="text-xs text-neutral-500">
              Skor baru menimpa skor final dan gate 60 diterapkan ulang. Perubahan dicatat
              di audit log.
            </p>

            <div className="grid grid-cols-2 gap-3">
              {CRITERIA.map(({ key, label }) => (
                <label key={key} className="text-sm text-neutral-700">
                  {label} (0–25)
                  <input
                    type="number"
                    min={0}
                    max={25}
                    step={1}
                    value={scores[key]}
                    onChange={(e) => setScores((s) => ({ ...s, [key]: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                  />
                </label>
              ))}
            </div>
            <p className="text-sm text-neutral-700">
              Total: <span className="font-semibold">{invalid ? "—" : total}</span>
              {!invalid && (
                <span className="ml-2 text-xs text-neutral-500">
                  {total >= 60 ? "→ Awaiting Assignment" : "→ Need Clarification"}
                </span>
              )}
            </p>

            <label className="block text-sm text-neutral-700">
              Alasan override (wajib)
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
              />
            </label>

            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                disabled={submitting}
                className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                           rounded-lg hover:bg-neutral-50 min-h-[36px]"
              >
                Batal
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className="px-3 py-1.5 text-sm font-medium text-white bg-primary-600 rounded-lg
                           hover:bg-primary-700 disabled:opacity-50 min-h-[36px]"
              >
                {submitting ? "Menyimpan..." : "Simpan override"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
