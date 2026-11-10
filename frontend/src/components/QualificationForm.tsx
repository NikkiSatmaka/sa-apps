"use client";

import {
  BUDGET_DIALOKASIKAN_CHOICES,
  JENIS_WORKLOAD_CHOICES,
  LINGKUNGAN_CHOICES,
  PERAN_PIC_CHOICES,
  TARGET_GO_LIVE_CHOICES,
  QualificationAnswers,
  QualificationErrors,
} from "@/lib/qualification";

/**
 * Form Kuesioner kualifikasi (langkah 2 pembuatan opportunity).
 * Komponen terkontrol: state jawaban dimiliki parent sehingga navigasi kembali ke
 * langkah 1 tidak menghilangkan isian. Tidak ada perhitungan skor di sini.
 */
interface Props {
  answers: QualificationAnswers;
  errors: QualificationErrors;
  onChange: (field: keyof QualificationAnswers, value: string) => void;
  disabled?: boolean;
}

const INPUT =
  "w-full px-3 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:opacity-50 disabled:bg-neutral-100";

export function QualificationForm({ answers, errors, onChange, disabled }: Props) {
  const cls = (f: keyof QualificationAnswers) =>
    `${INPUT} ${errors[f] ? "border-red-300 bg-red-50" : "border-neutral-300"}`;

  const label = (id: string, text: string, required = false) => (
    <label htmlFor={id} className="block text-sm font-medium text-neutral-700 mb-1">
      {text}{" "}
      {required ? (
        <span className="text-red-500">*</span>
      ) : (
        <span className="text-neutral-400 text-xs font-normal">(opsional)</span>
      )}
    </label>
  );

  const error = (f: keyof QualificationAnswers) =>
    errors[f] ? (
      <p id={`${f}-error`} className="text-xs text-red-600 mt-1" role="alert">
        {errors[f]}
      </p>
    ) : null;

  const select = (f: keyof QualificationAnswers, choices: readonly string[]) => (
    <select
      id={f}
      value={answers[f]}
      onChange={(e) => onChange(f, e.target.value)}
      disabled={disabled}
      className={cls(f)}
      aria-invalid={!!errors[f]}
      aria-describedby={errors[f] ? `${f}-error` : undefined}
    >
      <option value="">Pilih...</option>
      {choices.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );

  const text = (f: keyof QualificationAnswers, opts: { type?: string; placeholder?: string } = {}) => (
    <input
      id={f}
      type={opts.type ?? "text"}
      value={answers[f]}
      onChange={(e) => onChange(f, e.target.value)}
      disabled={disabled}
      placeholder={opts.placeholder}
      className={cls(f)}
      aria-invalid={!!errors[f]}
      aria-describedby={errors[f] ? `${f}-error` : undefined}
    />
  );

  const textarea = (f: keyof QualificationAnswers, placeholder?: string, hint?: string) => (
    <>
      <textarea
        id={f}
        rows={3}
        value={answers[f]}
        onChange={(e) => onChange(f, e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className={cls(f)}
        aria-invalid={!!errors[f]}
        aria-describedby={errors[f] ? `${f}-error` : undefined}
      />
      {hint && <p className="text-xs text-neutral-400 mt-1">{hint}</p>}
    </>
  );

  const section = (title: string, children: React.ReactNode) => (
    <fieldset className="bg-white rounded-lg border border-neutral-200 p-6 space-y-5">
      <legend className="text-sm font-semibold text-neutral-800 px-1">{title}</legend>
      {children}
    </fieldset>
  );

  return (
    <div className="space-y-6">
      {section(
        "Budget",
        <>
          <div>
            {label("mrr", "MRR (estimasi pendapatan bulanan, IDR)")}
            {text("mrr", { type: "number", placeholder: "Contoh: 5000000" })}
            {error("mrr")}
          </div>
          <div>
            {label("budget_dialokasikan", "Budget sudah dialokasikan/disetujui?", true)}
            {select("budget_dialokasikan", BUDGET_DIALOKASIKAN_CHOICES)}
            {error("budget_dialokasikan")}
          </div>
        </>
      )}

      {section(
        "Authority",
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              {label("pic_nama", "Nama PIC")}
              {text("pic_nama")}
              {error("pic_nama")}
            </div>
            <div>
              {label("pic_jabatan", "Jabatan PIC")}
              {text("pic_jabatan")}
              {error("pic_jabatan")}
            </div>
            <div>
              {label("pic_email", "Email PIC")}
              {text("pic_email", { type: "email" })}
              {error("pic_email")}
            </div>
          </div>
          <p className="text-xs text-neutral-400 -mt-2">
            Nama, jabatan, dan email PIC dinilai bila ketiganya diisi.
          </p>
          <div>
            {label("peran_pic", "Peran PIC dalam keputusan", true)}
            {select("peran_pic", PERAN_PIC_CHOICES)}
            {error("peran_pic")}
          </div>
          <div>
            {label("stakeholder_lain", "Stakeholder lain dalam keputusan")}
            {textarea("stakeholder_lain")}
            {error("stakeholder_lain")}
          </div>
        </>
      )}

      {section(
        "Need",
        <>
          <div>
            {label("masalah_bisnis", "Masalah bisnis yang ingin diselesaikan", true)}
            {textarea(
              "masalah_bisnis",
              "Jelaskan masalah bisnis customer secara faktual",
              `${answers.masalah_bisnis.trim().length} karakter — uraian yang lebih rinci (≥ 50 karakter) menambah skor.`
            )}
            {error("masalah_bisnis")}
          </div>
          <div>
            {label("jenis_workload", "Jenis workload", true)}
            {select("jenis_workload", JENIS_WORKLOAD_CHOICES)}
            {error("jenis_workload")}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              {label("lingkungan", "Lingkungan saat ini", true)}
              {select("lingkungan", LINGKUNGAN_CHOICES)}
              {error("lingkungan")}
            </div>
            <div>
              {label("skala", "Skala (jumlah server, volume data)", true)}
              {text("skala", { placeholder: "Contoh: 40 server, 20 TB" })}
              {error("skala")}
            </div>
          </div>
          <div>
            {label("persyaratan_khusus", "Persyaratan khusus (kepatuhan, SLA, integrasi, data residency)")}
            {textarea("persyaratan_khusus")}
            {error("persyaratan_khusus")}
          </div>
        </>
      )}

      {section(
        "Timeline & Kompetisi",
        <>
          <div>
            {label("target_go_live", "Target go-live / keputusan beli", true)}
            {select("target_go_live", TARGET_GO_LIVE_CHOICES)}
            {error("target_go_live")}
          </div>
          <div>
            {label("kompetitor", "Kompetitor/vendor lain")}
            {textarea("kompetitor")}
            {error("kompetitor")}
          </div>
        </>
      )}
    </div>
  );
}
