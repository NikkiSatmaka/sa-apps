"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { isPrivileged } from "@/lib/roles";

/**
 * Section penggantian orang project (ADR 0014): `product_pic`, `sales_pic`, `lead_sa`.
 * Hanya Lead_SA/Admin yang melihat tombolnya; backend tetap menegakkan hak aksesnya.
 */

interface Orang {
  id: string | null;
  name: string | null;
  email: string | null;
}

interface PeopleSectionProps {
  project: {
    id_project: string;
    product_pic?: Orang | null;
    sales_pic?: Orang | null;
    lead_sa?: Orang | null;
  };
  onChanged?: () => void;
}

type Field = "product_pic" | "sales_pic" | "lead_sa";

const FIELDS: { field: Field; label: string; role: string; boleKosong?: boolean }[] = [
  { field: "product_pic", label: "Product PIC", role: "Product" },
  { field: "sales_pic", label: "Sales PIC", role: "Sales", boleKosong: true },
  { field: "lead_sa", label: "Lead SA", role: "Lead_SA" },
];

function PilihOrang({
  field,
  label,
  role,
  boleKosong,
  semula,
  nilai,
  onChange,
}: {
  field: Field;
  label: string;
  role: string;
  boleKosong?: boolean;
  semula: Orang | null | undefined;
  nilai: string;
  onChange: (v: string) => void;
}) {
  const { data } = useSWR<Orang[]>(`/projects/users/search?role=${role}&limit=50`, fetcher);
  const opsi = [...(data ?? [])];
  // Pencarian mengecualikan diri sendiri: orang saat ini tetap harus bisa dipilih.
  if (semula?.id && !opsi.some((o) => o.id === semula.id)) opsi.unshift(semula);

  return (
    <div>
      <label htmlFor={`orang-${field}`} className="block text-xs font-medium text-neutral-600 mb-1">
        {label}
      </label>
      <select
        id={`orang-${field}`}
        value={nilai}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg min-h-[36px]"
      >
        {boleKosong && <option value="">Tanpa Sales</option>}
        {opsi.map((o) => (
          <option key={o.id} value={o.id ?? ""}>
            {o.name || o.email}
          </option>
        ))}
      </select>
    </div>
  );
}

export function PeopleSection({ project, onChanged }: PeopleSectionProps) {
  const { user } = useAuthStore();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nilai, setNilai] = useState<Record<Field, string>>({
    product_pic: "",
    sales_pic: "",
    lead_sa: "",
  });

  if (!isPrivileged(user)) return null;

  const semula = (f: Field) => project[f]?.id ?? "";
  const berubah = FIELDS.filter(({ field }) => nilai[field] !== semula(field));

  const buka = () => {
    setNilai({
      product_pic: semula("product_pic"),
      sales_pic: semula("sales_pic"),
      lead_sa: semula("lead_sa"),
    });
    setError(null);
    setEditing(true);
  };

  const simpan = async () => {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, string | null> = {};
      for (const { field } of berubah) body[field] = nilai[field] || null;
      await apiRequest(`/projects/${project.id_project}/people`, { method: "PATCH", body });
      setEditing(false);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal menyimpan perubahan.");
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="flex justify-end">
        <button
          type="button"
          onClick={buka}
          className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                     rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px]"
        >
          Ganti orang
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-5 space-y-3">
      <h2 className="text-sm font-semibold text-neutral-700">Ganti orang project</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {FIELDS.map((f) => (
          <PilihOrang
            key={f.field}
            {...f}
            semula={project[f.field]}
            nilai={nilai[f.field]}
            onChange={(v) => setNilai((n) => ({ ...n, [f.field]: v }))}
          />
        ))}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => setEditing(false)}
          disabled={saving}
          className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                     rounded-lg hover:bg-neutral-50 min-h-[36px] disabled:opacity-50"
        >
          Batal
        </button>
        <button
          type="button"
          onClick={simpan}
          disabled={saving || berubah.length === 0}
          className="px-3 py-1.5 text-sm font-medium text-white bg-primary-600 rounded-lg
                     hover:bg-primary-700 min-h-[36px] disabled:opacity-50"
        >
          {saving ? "Menyimpan..." : "Simpan"}
        </button>
      </div>
    </div>
  );
}
