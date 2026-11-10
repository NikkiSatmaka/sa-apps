"use client";

import {
  layoutRows,
  type QualificationAnswers,
  type QualificationErrors,
  type QualificationSchema,
  type QuestionDef,
} from "@/lib/qualification";

/**
 * Form Kuesioner kualifikasi (langkah 2 pembuatan opportunity; juga form edit).
 * Dirender sepenuhnya dari skema backend (label, tipe, wajib, pilihan, petunjuk, tata letak).
 * Komponen terkontrol: state jawaban dimiliki parent sehingga navigasi kembali ke
 * langkah 1 tidak menghilangkan isian. Tidak ada perhitungan skor di sini.
 */
interface Props {
  schema: QualificationSchema;
  answers: QualificationAnswers;
  errors: QualificationErrors;
  onChange: (field: string, value: string) => void;
  disabled?: boolean;
}

const INPUT =
  "w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:opacity-50 disabled:bg-neutral-100";

const GRID_COLS: Record<number, string> = {
  2: "grid grid-cols-1 sm:grid-cols-2 gap-4",
  3: "grid grid-cols-1 sm:grid-cols-3 gap-4",
};

export function QualificationForm({ schema, answers, errors, onChange, disabled }: Props) {
  const value = (f: string) => answers[f] ?? "";
  const cls = (f: string) => `${INPUT} ${errors[f] ? "border-red-300 bg-red-50" : "border-neutral-300"}`;
  const aria = (f: string) => ({
    "aria-invalid": !!errors[f],
    "aria-describedby": errors[f] ? `${f}-error` : undefined,
  });

  const field = (q: QuestionDef) => {
    const f = q.name;
    let input: React.ReactNode;
    if (q.type === "choice") {
      input = (
        <select
          id={f}
          value={value(f)}
          onChange={(e) => onChange(f, e.target.value)}
          disabled={disabled}
          className={cls(f)}
          {...aria(f)}
        >
          <option value="">Pilih...</option>
          {(q.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      );
    } else if (q.type === "text") {
      const hint = q.show_char_count
        ? `${value(f).trim().length} karakter${q.hint ? ` — ${q.hint}` : ""}`
        : q.hint;
      input = (
        <>
          <textarea
            id={f}
            rows={3}
            value={value(f)}
            onChange={(e) => onChange(f, e.target.value)}
            disabled={disabled}
            placeholder={q.placeholder ?? undefined}
            className={cls(f)}
            {...aria(f)}
          />
          {hint && <p className="text-xs text-neutral-400 mt-1">{hint}</p>}
        </>
      );
    } else {
      input = (
        <input
          id={f}
          type={q.type === "number" ? "number" : q.type === "email" ? "email" : "text"}
          value={value(f)}
          onChange={(e) => onChange(f, e.target.value)}
          disabled={disabled}
          placeholder={q.placeholder ?? undefined}
          className={cls(f)}
          {...aria(f)}
        />
      );
    }
    return (
      <div key={f}>
        <label htmlFor={f} className="block text-sm font-medium text-neutral-700 mb-1">
          {q.label}{" "}
          {q.required ? (
            <span className="text-red-500">*</span>
          ) : (
            <span className="text-neutral-400 text-xs font-normal">(opsional)</span>
          )}
        </label>
        {input}
        {q.type !== "text" && q.hint && <p className="text-xs text-neutral-400 mt-1">{q.hint}</p>}
        {errors[f] && (
          <p id={`${f}-error`} className="text-xs text-red-600 mt-1" role="alert">
            {errors[f]}
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {schema.groups.map((g) => {
        const rows = layoutRows(schema, g.key);
        if (rows.length === 0) return null;
        return (
          // Bukan <fieldset>/<legend>: browser menggambar legend tepat di garis border sehingga
          // judul terlihat keluar dari kotak. Section + heading menjaga judul di dalam kotak
          // dan tetap diumumkan ke pembaca layar lewat aria-labelledby.
          <section
            key={g.key}
            aria-labelledby={`qualification-group-${g.key}`}
            className="bg-white rounded-lg border border-neutral-200 p-6 space-y-5"
          >
            <h3 id={`qualification-group-${g.key}`} className="text-sm font-semibold text-neutral-800">
              {g.title}
            </h3>
            {rows.map((row) => {
              const first = row.questions[0].name;
              const cols = GRID_COLS[row.questions.length];
              return (
                <div key={first} className="space-y-5">
                  {cols ? <div className={cols}>{row.questions.map(field)}</div> : row.questions.map(field)}
                  {row.hint && <p className="text-xs text-neutral-400 -mt-2">{row.hint}</p>}
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
