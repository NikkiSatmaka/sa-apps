"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import {
  keepRequirementVersion,
  regenerateRequirement,
} from "@/lib/api/documents";

/**
 * Banner "sumber berubah" untuk Requirement yang di-override atau Final (#37).
 *
 * Konten tidak berubah sampai pengguna memilih salah satu aksi:
 * - "Generate ulang (timpa edit saya)": endpoint regenerate #34 (menghapus override).
 * - "Pertahankan versi saya": hash sumber diperbarui tanpa mengubah konten.
 * Hanya dirender untuk peran yang diizinkan (keputusan ada di pemanggil; backend menegakkan).
 */

interface RequirementSourceChangedBannerProps {
  projectId: string;
  /** Dipanggil setelah aksi berhasil agar daftar dokumen dimuat ulang */
  onChanged: () => void;
}

export function RequirementSourceChangedBanner({
  projectId,
  onChanged,
}: RequirementSourceChangedBannerProps) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState<"regenerate" | "keep" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: "regenerate" | "keep") => {
    setBusy(action);
    setError(null);
    try {
      if (action === "regenerate") {
        await regenerateRequirement(projectId);
        // Muat ulang status agar bagian status mulai polling sampai generate selesai
        await mutate(`/projects/${projectId}/requirement-status`);
      } else {
        await keepRequirementVersion(projectId);
      }
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Aksi gagal dijalankan.");
    } finally {
      setBusy(null);
    }
  };

  const buttonClass =
    "px-3 py-1.5 rounded-lg text-sm font-medium border min-h-[36px] disabled:opacity-50";

  return (
    <div
      className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
      role="alert"
    >
      <p>
        Sumber Requirement (jawaban kuesioner atau Source document) berubah
        sejak Requirement ini dibuat. Isi Requirement belum diubah. Pilih
        tindakan:
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => run("regenerate")}
          disabled={busy !== null}
          className={`${buttonClass} border-amber-400 bg-white text-amber-900 hover:bg-amber-100`}
        >
          {busy === "regenerate" ? "Memulai..." : "Generate ulang (timpa edit saya)"}
        </button>
        <button
          type="button"
          onClick={() => run("keep")}
          disabled={busy !== null}
          className={`${buttonClass} border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50`}
        >
          {busy === "keep" ? "Menyimpan..." : "Pertahankan versi saya"}
        </button>
      </div>
      {error && <p className="mt-2 text-red-700">{error}</p>}
    </div>
  );
}
