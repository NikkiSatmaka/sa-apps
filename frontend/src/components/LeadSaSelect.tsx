"use client";

import { useId } from "react";
import type { AvailableSA } from "@/lib/api/assignment";

/**
 * Dropdown "Lead SA" untuk modal assign/reassign (ADR 0014; tiket #135).
 *
 * Opsi hanya user berrole Lead_SA dari daftar `/sa/available` (field `role`). `value` kosong
 * berarti belum dipilih; modal pemanggil yang menentukan default dan kapan wajib memilih.
 */

interface LeadSaSelectProps {
  /** Daftar kandidat dari `/sa/available`; disaring ke role Lead_SA di sini. */
  kandidat: AvailableSA[];
  /** ID Lead SA terpilih; "" bila belum dipilih. */
  value: string;
  onChange: (id: string) => void;
  /** Terkunci (mis. reassign pada proyek yang sudah punya lead_sa). */
  disabled?: boolean;
  /** Opsi bawaan bila `value` tidak ada di daftar (mis. lead_sa saat ini belum termuat). */
  namaSaatIni?: string | null;
  /** Teks bantuan di bawah dropdown. */
  petunjuk?: string;
}

export function LeadSaSelect({ kandidat, value, onChange, disabled, namaSaatIni, petunjuk }: LeadSaSelectProps) {
  const id = useId();
  const leads = kandidat.filter((k) => k.role === "Lead_SA");
  const adaDiDaftar = leads.some((l) => l.id === value);

  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-sm font-medium text-neutral-700 mb-1">
        Lead SA
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full min-h-[44px] rounded-lg border border-neutral-300 bg-white px-3 text-sm
                   text-neutral-900 disabled:bg-neutral-100 disabled:text-neutral-500"
      >
        <option value="">Pilih Lead SA…</option>
        {value && !adaDiDaftar && <option value={value}>{namaSaatIni || value}</option>}
        {leads.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </select>
      {petunjuk && <p className="text-xs text-neutral-500 mt-1">{petunjuk}</p>}
    </div>
  );
}
