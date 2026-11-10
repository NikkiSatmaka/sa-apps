"use client";

import { useState } from "react";
import {
  addRequirementItem,
  deleteRequirementItem,
  updateRequirementItem,
  type Document,
  type RequirementItem,
  type RequirementKategori,
} from "@/lib/api/documents";

/**
 * Editor butir Requirement per butir (tambah/ubah/hapus) untuk peran yang diizinkan (#36):
 * SA yang ditugaskan, Lead_SA, dan Admin. Peran lain memakai RequirementItemsView (read-only).
 * Setiap simpan menyetel `is_overridden` di backend; pemanggil me-refresh daftar dokumen.
 */

const KATEGORI_ORDER: RequirementKategori[] = [
  "Fungsional",
  "Teknis",
  "Kepatuhan",
  "Integrasi",
  "Timeline",
  "Asumsi",
];
const MAX_BUTIR = 1000;

interface RequirementItemsEditorProps {
  projectId: string;
  doc: Document;
  /** Dipanggil setelah simpan berhasil (refresh data) */
  onChanged: () => void | Promise<unknown>;
  onError: (message: string) => void;
}

interface Draft {
  /** null = butir baru */
  id: string | null;
  kategori: RequirementKategori;
  butir: string;
}

export function RequirementItemsEditor({
  projectId,
  doc,
  onChanged,
  onError,
}: RequirementItemsEditorProps) {
  const items: RequirementItem[] = doc.content ?? [];
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);

  const butirKosong = draft ? draft.butir.trim().length === 0 : true;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await onChanged();
      setDraft(null);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Gagal menyimpan butir Requirement");
    } finally {
      setBusy(false);
    }
  }

  function save() {
    if (!draft || butirKosong) return;
    const input = { kategori: draft.kategori, butir: draft.butir.trim() };
    void run(() =>
      draft.id
        ? updateRequirementItem(projectId, draft.id, input)
        : addRequirementItem(projectId, input)
    );
  }

  function remove(item: RequirementItem) {
    if (!window.confirm("Hapus butir ini?")) return;
    void run(() => deleteRequirementItem(projectId, item.id));
  }

  function renderForm() {
    if (!draft) return null;
    return (
      <div className="mt-2 rounded border border-neutral-200 bg-white p-3 space-y-2">
        <label className="block text-xs font-medium text-neutral-600">
          Kategori
          <select
            value={draft.kategori}
            onChange={(e) =>
              setDraft({ ...draft, kategori: e.target.value as RequirementKategori })
            }
            className="mt-1 block w-full rounded border border-neutral-300 px-2 py-1 text-sm"
          >
            {KATEGORI_ORDER.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Butir
          <textarea
            value={draft.butir}
            maxLength={MAX_BUTIR}
            rows={3}
            onChange={(e) => setDraft({ ...draft, butir: e.target.value })}
            className="mt-1 block w-full rounded border border-neutral-300 px-2 py-1 text-sm"
          />
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={save}
            disabled={busy || butirKosong}
            className="rounded bg-primary-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            {busy ? "Menyimpan..." : "Simpan"}
          </button>
          <button
            type="button"
            onClick={() => setDraft(null)}
            disabled={busy}
            className="rounded border border-neutral-300 px-3 py-1 text-xs"
          >
            Batal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3" aria-label="Edit butir Requirement">
      {doc.source_truncated && (
        <p
          className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2"
          role="status"
        >
          Requirement dibuat dari teks yang terpotong. Periksa sumber aslinya.
        </p>
      )}
      {doc.is_overridden && (
        <p className="text-xs text-neutral-500">Sudah diedit manual.</p>
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
            <ul className="mt-1 space-y-1 text-sm text-neutral-800">
              {butir.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-2">
                  <span>{item.butir}</span>
                  <span className="flex shrink-0 gap-2 text-xs">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        setDraft({ id: item.id, kategori: item.kategori, butir: item.butir })
                      }
                      className="text-primary-600 hover:underline"
                      aria-label={`Ubah butir: ${item.butir}`}
                    >
                      Ubah
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => remove(item)}
                      className="text-red-600 hover:underline"
                      aria-label={`Hapus butir: ${item.butir}`}
                    >
                      Hapus
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      {renderForm()}

      {!draft && (
        <button
          type="button"
          disabled={busy}
          onClick={() => setDraft({ id: null, kategori: "Fungsional", butir: "" })}
          className="rounded border border-neutral-300 px-3 py-1 text-xs font-medium"
        >
          + Tambah butir
        </button>
      )}
    </div>
  );
}
