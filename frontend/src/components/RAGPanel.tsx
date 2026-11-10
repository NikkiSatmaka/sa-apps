"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import type { Recommendation } from "@/lib/api/handover";

/**
 * Panel "Referensi Serupa" — RAG Recommendation
 *
 * Ditampilkan di sidebar halaman pembuatan dokumen.
 * Menampilkan max 5 rekomendasi dokumen dari proyek Closed-Win
 * yang memiliki use_case_tags serupa.
 *
 * States:
 * - Loading: skeleton placeholder
 * - Empty (no tags): pesan scoring belum selesai
 * - Empty (no results): pesan belum ada referensi
 * - Data: daftar rekomendasi dengan project name, doc type, tags, link GDrive
 *
 * Requirements: 15.1, 15.3, 15.4
 */

interface RAGPanelProps {
  /** ID proyek yang sedang dikerjakan */
  projectId: string;
  /** Apakah proyek sudah punya use_case_tags (sudah scoring) */
  hasTags?: boolean;
}

export function RAGPanel({ projectId, hasTags = true }: RAGPanelProps) {
  // Fetch rekomendasi dari API hanya jika proyek sudah punya tags
  const {
    data: recommendations,
    error,
    isLoading,
  } = useSWR<Recommendation[]>(
    hasTags ? `/projects/${projectId}/recommendations` : null,
    fetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000, // Cache 30 detik
    }
  );

  // Jika proyek belum punya tags (belum melalui scoring)
  if (!hasTags) {
    return (
      <aside
        className="bg-white border border-neutral-200 rounded-lg p-4"
        aria-label="Panel Referensi Serupa"
      >
        <h3 className="text-sm font-semibold text-neutral-800 mb-3">
          Referensi Serupa
        </h3>
        <p className="text-xs text-neutral-500 italic">
          Rekomendasi akan tersedia setelah scoring selesai
        </p>
      </aside>
    );
  }

  return (
    <aside
      className="bg-white border border-neutral-200 rounded-lg p-4"
      aria-label="Panel Referensi Serupa"
    >
      {/* Header panel */}
      <h3 className="text-sm font-semibold text-neutral-800 mb-3">
        Referensi Serupa
      </h3>

      {/* Loading skeleton */}
      {isLoading && (
        <div className="space-y-3" aria-busy="true" aria-label="Memuat rekomendasi">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse space-y-2">
              <div className="h-3.5 bg-neutral-200 rounded w-3/4" />
              <div className="h-3 bg-neutral-100 rounded w-1/2" />
              <div className="flex gap-1.5">
                <div className="h-5 bg-neutral-100 rounded-full w-14" />
                <div className="h-5 bg-neutral-100 rounded-full w-10" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <p className="text-xs text-red-600" role="alert">
          Gagal memuat rekomendasi.
        </p>
      )}

      {/* Empty state — tidak ada proyek serupa */}
      {!isLoading && !error && recommendations && recommendations.length === 0 && (
        <p className="text-xs text-neutral-500 italic">
          Belum ada referensi serupa
        </p>
      )}

      {/* Daftar rekomendasi (max 5) */}
      {!isLoading && !error && recommendations && recommendations.length > 0 && (
        <ul className="space-y-3" aria-label="Daftar rekomendasi dokumen">
          {recommendations
            .filter((rec) => !!rec.gdrive_link)
            .slice(0, 5)
            .map((rec, index) => (
            <li key={`${rec.id_project}-${rec.doc_type}-${index}`}>
              <a
                href={rec.gdrive_link ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                className="block p-3 rounded-lg border border-neutral-100 
                           hover:border-primary-200 hover:bg-primary-50/50
                           transition-all duration-100 group"
                aria-label={`Buka dokumen ${rec.doc_type} dari proyek ${rec.project_name}`}
              >
                {/* Nama proyek */}
                <p className="text-sm font-medium text-neutral-800 group-hover:text-primary-700 truncate">
                  {rec.project_name}
                </p>

                {/* Tipe dokumen */}
                <p className="text-xs text-neutral-500 mt-0.5">
                  {rec.doc_type}
                  <span className="ml-2 text-neutral-300">•</span>
                  <span className="ml-2 text-primary-600 group-hover:underline">
                    Buka di Drive ↗
                  </span>
                </p>

                {/* Use case tags sebagai badges */}
                {rec.use_case_tags && rec.use_case_tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {rec.use_case_tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-1.5 py-0.5 bg-neutral-100 text-neutral-600 
                                   text-[10px] rounded-full leading-tight"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </a>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
