"use client";

/**
 * Tampilan kualifikasi di detail proyek (read-only).
 * Proyek baru: jawaban kuesioner + sub-skor + feedback (skor < 60).
 * Proyek lama (legacy): metadata BANT lama apa adanya, tanpa backfill.
 */

import { ANSWER_LABELS, type QualificationView } from "@/lib/qualification";

const SUB_SCORE_LABELS: [keyof NonNullable<QualificationView["sub_scores"]>, string][] = [
  ["budget", "Budget"],
  ["authority", "Authority"],
  ["need", "Need"],
  ["timeline", "Timeline"],
];

const KOSONG = <span className="text-neutral-400">—</span>;

function formatTanggal(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
}

function SubScores({ q }: { q: QualificationView }) {
  if (!q.sub_scores) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold text-neutral-600 mb-2">Sub-skor BANT</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        {SUB_SCORE_LABELS.map(([key, label]) => (
          <div key={key} className="p-3 bg-neutral-50 rounded-lg">
            <p className="text-xs font-medium text-neutral-500 mb-1">{label}</p>
            <p className="text-neutral-800 font-medium">{q.sub_scores![key]}/25</p>
          </div>
        ))}
      </div>
      {q.feedback && (
        <div
          role="note"
          className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 whitespace-pre-line"
        >
          {q.feedback}
        </div>
      )}
    </div>
  );
}

export function QualificationSection({
  qualification,
  targetSubmit,
}: {
  qualification: QualificationView | undefined;
  targetSubmit: string | null;
}) {
  if (!qualification) return null;
  const q = qualification;

  if (!q.legacy && q.answers) {
    return (
      <div className="bg-white border border-neutral-200 rounded-lg p-5 space-y-4">
        <h2 className="text-sm font-semibold text-neutral-700">Kuesioner Kualifikasi</h2>
        <SubScores q={q} />
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <div className="p-3 bg-neutral-50 rounded-lg">
            <dt className="text-xs font-medium text-neutral-500 mb-1">Target submit</dt>
            <dd className="text-neutral-800">{targetSubmit ? formatTanggal(targetSubmit) : KOSONG}</dd>
          </div>
          {ANSWER_LABELS.map(([key, label]) => {
            const value = q.answers![key];
            const kosong = value === null || value === undefined || value === "";
            return (
              <div key={key} className="p-3 bg-neutral-50 rounded-lg">
                <dt className="text-xs font-medium text-neutral-500 mb-1">{label}</dt>
                <dd className="text-neutral-800 whitespace-pre-line">
                  {kosong
                    ? KOSONG
                    : key === "mrr"
                      ? `Rp ${Number(value).toLocaleString("id-ID")}`
                      : String(value)}
                </dd>
              </div>
            );
          })}
        </dl>
      </div>
    );
  }

  // Proyek lama: tampilkan metadata lama sebagai "legacy"; tidak ada data yang diubah.
  const d = q.legacy_data;
  if (!d && !q.sub_scores) return null;
  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-neutral-700">Detail BANT</h2>
        <span className="text-xs px-2 py-0.5 rounded bg-neutral-100 text-neutral-600">Legacy</span>
      </div>
      <p className="text-xs text-neutral-500">
        Proyek ini dibuat sebelum Kuesioner kualifikasi; data lama ditampilkan apa adanya.
      </p>
      <SubScores q={q} />
      {d && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div className="p-3 bg-neutral-50 rounded-lg">
            <p className="text-xs font-medium text-neutral-500 mb-1">Budget (MRR)</p>
            <p className="text-neutral-800 font-medium">
              {d.budget_mrr ? `Rp ${Number(d.budget_mrr).toLocaleString("id-ID")}` : KOSONG}
            </p>
          </div>
          <div className="p-3 bg-neutral-50 rounded-lg">
            <p className="text-xs font-medium text-neutral-500 mb-1">PIC Customer</p>
            {d.pic_name ? (
              <div>
                <p className="text-neutral-800 font-medium">{d.pic_name}</p>
                <p className="text-xs text-neutral-500">
                  {d.pic_position}
                  {d.pic_email && ` — ${d.pic_email}`}
                </p>
              </div>
            ) : (
              KOSONG
            )}
          </div>
          <div className="p-3 bg-neutral-50 rounded-lg md:col-span-2">
            <p className="text-xs font-medium text-neutral-500 mb-1">Kebutuhan Teknis</p>
            <p className="text-neutral-800 whitespace-pre-line">{d.need_description || KOSONG}</p>
          </div>
          <div className="p-3 bg-neutral-50 rounded-lg">
            <p className="text-xs font-medium text-neutral-500 mb-1">Target Timeline</p>
            <p className="text-neutral-800">
              {d.timeline_target
                ? formatTanggal(d.timeline_target)
                : targetSubmit
                  ? formatTanggal(targetSubmit)
                  : KOSONG}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
