"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "./LoadError";

/**
 * Thread komentar project (#125, spec §2.5 dan A5). Terpisah dari Project Story (log aktivitas SA).
 *
 * - Dibaca semua pengguna terautentikasi; urutan kronologis naik dari server.
 * - Menulis: hak ditentukan server (orang yang ditugaskan, Lead_SA, Admin). UI tidak menebak
 *   hubungan per project; penolakan server (mis. 403) ditampilkan apa adanya.
 * - `readOnly` (project `Closed`/`Lost`): form diganti keterangan; server tetap menolak dengan 409.
 * - Komentar tidak dapat diedit atau dihapus.
 *
 * Endpoint:
 * - GET  /projects/{id}/comments
 * - POST /projects/{id}/comments
 */

const BODY_MAKS = 4000;

interface Komentar {
  id_comment: string;
  id_project: string;
  author_id: string;
  author_name: string | null;
  author_role: string | null;
  body: string;
  created_at: string;
}

interface ProjectCommentsProps {
  projectId: string;
  readOnly?: boolean;
}

function formatWaktu(iso: string): string {
  return new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

export function ProjectComments({ projectId, readOnly = false }: ProjectCommentsProps) {
  const [isian, setIsian] = useState("");
  const [mengirim, setMengirim] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data, mutate, isLoading, error: loadError } = useSWR<{ items: Komentar[]; total: number }>(
    `/projects/${projectId}/comments`,
    fetcher
  );

  const gagalMemuat = Boolean(loadError) && !data;
  const items = data?.items ?? [];
  const body = isian.trim();

  const kirim = async () => {
    if (!body || mengirim) return;
    setMengirim(true);
    setError(null);
    try {
      await apiRequest(`/projects/${projectId}/comments`, { method: "POST", body: { body } });
      setIsian("");
      await mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengirim komentar.");
    } finally {
      setMengirim(false);
    }
  };

  return (
    <section className="bg-white border border-neutral-200 rounded-lg p-5" aria-labelledby="komentar-judul">
      <div className="flex items-center justify-between mb-3">
        <h2 id="komentar-judul" className="text-sm font-semibold text-neutral-700">
          Komentar
        </h2>
        {data && <span className="text-xs text-neutral-500">{data.total} komentar</span>}
      </div>

      {isLoading && (
        <div className="space-y-2 animate-pulse" aria-hidden="true">
          <div className="h-12 bg-neutral-100 rounded-lg" />
          <div className="h-12 bg-neutral-100 rounded-lg" />
        </div>
      )}

      {gagalMemuat && <LoadError message="Gagal memuat komentar." onRetry={() => mutate()} />}

      {!isLoading && !gagalMemuat && items.length === 0 && (
        <p className="text-sm text-neutral-500 text-center py-3">Belum ada komentar.</p>
      )}

      {items.length > 0 && (
        <ul className="space-y-3 mb-4">
          {items.map((k) => (
            <li key={k.id_comment} className="p-3 bg-neutral-50 rounded-lg border border-neutral-100">
              <div className="flex flex-wrap items-baseline gap-x-2 mb-1">
                <span className="text-sm font-medium text-neutral-900">{k.author_name ?? "Pengguna"}</span>
                {k.author_role && <span className="text-xs text-neutral-500">{k.author_role}</span>}
                <time className="text-xs text-neutral-400" dateTime={k.created_at}>
                  {formatWaktu(k.created_at)}
                </time>
              </div>
              <p className="text-sm text-neutral-700 whitespace-pre-wrap break-words">{k.body}</p>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {readOnly ? (
        <p className="text-sm text-neutral-500">
          Proyek berstatus Closed atau Lost: komentar baru tidak dapat ditambahkan.
        </p>
      ) : (
        <div className="space-y-2">
          <label htmlFor="komentar-baru" className="text-xs font-medium text-neutral-600 block">
            Tulis komentar
          </label>
          <textarea
            id="komentar-baru"
            value={isian}
            maxLength={BODY_MAKS}
            rows={3}
            disabled={mengirim}
            onChange={(e) => setIsian(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                       focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />
          <button
            type="button"
            onClick={kirim}
            disabled={!body || mengirim}
            className="px-3 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg
                       hover:bg-primary-700 transition-colors min-h-[36px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mengirim ? "Mengirim..." : "Kirim"}
          </button>
        </div>
      )}
    </section>
  );
}
