"use client";

/**
 * Section Source document — daftar file MoM/RFP yang di-upload saat intake
 * beserta status ekstraksi teksnya (pending/extracted/empty/failed).
 * Data berasal dari detail proyek (akses mengikuti akses proyek).
 */

export interface SourceDocumentItem {
  id: string;
  filename: string;
  doc_type: "MoM" | "RFP";
  size_bytes: number;
  extraction_status: "pending" | "extracted" | "empty" | "failed";
  truncated: boolean;
  text_length: number;
  created_at: string | null;
  updated_at: string | null;
}

const STATUS_LABEL: Record<SourceDocumentItem["extraction_status"], { text: string; cls: string }> = {
  pending: { text: "Sedang diekstrak", cls: "bg-amber-100 text-amber-700" },
  extracted: { text: "Terekstrak", cls: "bg-green-100 text-green-700" },
  empty: { text: "Tanpa teks", cls: "bg-neutral-100 text-neutral-600" },
  failed: { text: "Gagal diekstrak", cls: "bg-red-100 text-red-700" },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function SourceDocumentSection({ documents }: { documents: SourceDocumentItem[] }) {
  if (!documents || documents.length === 0) return null;

  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-5">
      <h2 className="text-base font-semibold text-neutral-800 mb-3">Source Document</h2>
      <ul className="divide-y divide-neutral-100" aria-label="Daftar Source document">
        {documents.map((d) => {
          const st = STATUS_LABEL[d.extraction_status];
          return (
            <li key={d.id} className="py-2 flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-neutral-800 truncate">{d.filename}</p>
                <p className="text-xs text-neutral-500">
                  {d.doc_type} · {formatSize(d.size_bytes)}
                  {d.extraction_status === "extracted" && ` · ${d.text_length.toLocaleString("id-ID")} karakter`}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {d.truncated && (
                  <span
                    className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700"
                    title="Respons LLM berhenti karena batas token; teks mungkin tidak lengkap"
                  >
                    Terpotong
                  </span>
                )}
                <span className={`text-xs px-2 py-0.5 rounded-full ${st.cls}`}>{st.text}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
