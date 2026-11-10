import type { Document, RequirementKategori } from "@/lib/api/documents";

/**
 * Tampilan read-only butir Requirement per kategori (#33).
 *
 * Requirement adalah konten turunan AI (tanpa file Drive). Edit per butir, banner sumber
 * berubah, dan tombol generate ulang dikerjakan di tiket lain (5B-2..5B-5).
 */

// Urutan tampil kategori (selaras kontrak backend)
const KATEGORI_ORDER: RequirementKategori[] = [
  "Fungsional",
  "Teknis",
  "Kepatuhan",
  "Integrasi",
  "Timeline",
  "Asumsi",
];

interface RequirementItemsViewProps {
  doc: Document;
}

export function RequirementItemsView({ doc }: RequirementItemsViewProps) {
  const items = doc.content ?? [];

  return (
    <div className="space-y-3" aria-label="Butir Requirement">
      {doc.source_truncated && (
        <p
          className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2"
          role="status"
        >
          Requirement dibuat dari teks yang terpotong. Periksa sumber aslinya.
        </p>
      )}

      {items.length === 0 && (
        <p className="text-xs text-neutral-500 italic">Belum ada butir.</p>
      )}

      {KATEGORI_ORDER.map((kategori) => {
        const butir = items.filter((item) => item.kategori === kategori);
        if (butir.length === 0) return null;
        return (
          <section key={kategori}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              {kategori}
            </h3>
            <ul className="mt-1 list-disc pl-5 space-y-0.5 text-sm text-neutral-800">
              {butir.map((item) => (
                <li key={item.id}>{item.butir}</li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
