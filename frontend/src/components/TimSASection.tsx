"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "./LoadError";
import { useAuthStore } from "@/store/auth";
import type { AvailableSA } from "@/lib/api/assignment";
import { isPrivileged as isPrivilegedUser } from "@/lib/roles";

/**
 * Section "Tim SA" — SA utama (penanggung jawab) dan SA tambahan per project (ADR 0014).
 *
 * Semua peran melihat tim (membaca project terbuka). Hanya Lead_SA/admin (`is_admin`) yang
 * melihat kontrol kelola: tambah SA tambahan, lepas SA tambahan, ganti SA utama (SA lama dilepas
 * atau dipertahankan sebagai SA tambahan), dan menaikkan SA tambahan menjadi SA utama.
 * SA utama tidak punya tombol "Lepas": project minimal punya satu SA, jadi SA utama diganti,
 * bukan dilepas.
 *
 * Endpoint:
 * - GET    /projects/{id}/tim-sa
 * - POST   /projects/{id}/tim-sa                 { user_id }
 * - DELETE /projects/{id}/tim-sa/{user_id}
 * - PUT    /projects/{id}/tim-sa/utama           { user_id, pertahankan_sebagai_tambahan }
 * - GET    /sa/available (kandidat; hanya di-fetch untuk Lead_SA/admin)
 */

interface AnggotaSA {
  id: string;
  name: string;
  email: string;
}

interface SATambahan extends AnggotaSA {
  added_by: string;
  created_at: string;
}

interface TimSA {
  sa_utama: AnggotaSA | null;
  sa_tambahan: SATambahan[];
}

interface TimSASectionProps {
  projectId: string;
}

export function TimSASection({ projectId }: TimSASectionProps) {
  const { user } = useAuthStore();
  const bisaKelola = isPrivilegedUser(user);

  const [panel, setPanel] = useState<"tambah" | "ganti" | null>(null);
  const [pilihan, setPilihan] = useState("");
  const [pertahankan, setPertahankan] = useState(false);
  const [sibuk, setSibuk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const url = `/projects/${projectId}/tim-sa`;
  const { data: tim, mutate, isLoading, error: loadError } = useSWR<TimSA>(url, fetcher);
  const { data: kandidat } = useSWR<AvailableSA[]>(bisaKelola ? "/sa/available" : null, fetcher);

  const gagalMemuat = Boolean(loadError) && !tim;
  const utama = tim?.sa_utama ?? null;
  const tambahan = tim?.sa_tambahan ?? [];
  const anggotaIds = new Set([...(utama ? [utama.id] : []), ...tambahan.map((s) => s.id)]);

  // Tambah: kandidat yang belum di tim. Ganti utama: semua kandidat selain SA utama saat ini.
  const kandidatTambah = (kandidat ?? []).filter((sa) => !anggotaIds.has(sa.id));
  const kandidatUtama = (kandidat ?? []).filter((sa) => sa.id !== utama?.id);

  const tutupPanel = () => {
    setPanel(null);
    setPilihan("");
    setPertahankan(false);
  };

  const jalankan = async (aksi: () => Promise<unknown>, pesanGagal: string, tutup = false) => {
    setSibuk(true);
    setError(null);
    try {
      await aksi();
      if (tutup) tutupPanel();
      await mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : pesanGagal);
    } finally {
      setSibuk(false);
    }
  };

  const tambahSA = () =>
    jalankan(
      () => apiRequest(url, { method: "POST", body: { user_id: pilihan } }),
      "Gagal menambahkan SA ke tim.",
      true
    );

  const lepasSA = (sa: AnggotaSA) => {
    if (!confirm(`Lepas ${sa.name} dari tim SA proyek ini?`)) return;
    return jalankan(
      () => apiRequest(`${url}/${sa.id}`, { method: "DELETE" }),
      "Gagal melepas SA dari tim."
    );
  };

  const gantiUtama = (userId: string, pertahankanLama: boolean) =>
    jalankan(
      () =>
        apiRequest(`${url}/utama`, {
          method: "PUT",
          body: { user_id: userId, pertahankan_sebagai_tambahan: pertahankanLama },
        }),
      "Gagal mengganti SA utama.",
      true
    );

  const bukaPanel = (jenis: "tambah" | "ganti") => {
    setError(null);
    setPilihan("");
    setPertahankan(false);
    setPanel((cur) => (cur === jenis ? null : jenis));
  };

  const tombolKecil =
    "px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors min-h-[32px] " +
    "disabled:opacity-50 disabled:cursor-not-allowed";

  return (
    <section
      className="bg-white border border-neutral-200 rounded-lg p-5"
      aria-labelledby="tim-sa-heading"
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 id="tim-sa-heading" className="text-sm font-semibold text-neutral-700">
            Tim SA
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            SA utama bertanggung jawab; SA tambahan punya hak setara.
          </p>
        </div>
        {bisaKelola && utama && (
          <button
            type="button"
            onClick={() => bukaPanel("tambah")}
            aria-expanded={panel === "tambah"}
            className={`${tombolKecil} text-primary-600 border-primary-200 hover:bg-primary-50`}
          >
            + Tambah SA
          </button>
        )}
      </div>

      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {isLoading && (
        <div className="space-y-2 animate-pulse" aria-hidden="true">
          <div className="h-12 bg-neutral-100 rounded-lg" />
          <div className="h-12 bg-neutral-100 rounded-lg" />
        </div>
      )}

      {gagalMemuat && <LoadError message="Gagal memuat tim SA." onRetry={() => mutate()} />}

      {tim && (
        <>
          {/* Panel tambah SA tambahan */}
          {bisaKelola && panel === "tambah" && (
            <div className="mb-4 p-3 bg-neutral-50 rounded-lg border border-neutral-200 space-y-3">
              <div>
                <label
                  htmlFor="tim-sa-tambah"
                  className="text-xs font-medium text-neutral-600 mb-1 block"
                >
                  Pilih SA:
                </label>
                <select
                  id="tim-sa-tambah"
                  value={pilihan}
                  onChange={(e) => setPilihan(e.target.value)}
                  disabled={sibuk}
                  className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                             focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                >
                  <option value="">— Pilih SA —</option>
                  {kandidatTambah.map((sa) => (
                    <option key={sa.id} value={sa.id}>
                      {sa.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={tambahSA}
                  disabled={!pilihan || sibuk}
                  className="flex-1 px-3 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg
                             hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {sibuk ? "Menyimpan..." : "Tambah ke tim"}
                </button>
                <button
                  type="button"
                  onClick={tutupPanel}
                  className="px-3 py-2 text-sm text-neutral-600 border border-neutral-300 rounded-lg hover:bg-neutral-50"
                >
                  Batal
                </button>
              </div>
            </div>
          )}

          <ul className="space-y-2">
            {utama ? (
              <li
                aria-label={`SA utama: ${utama.name}`}
                className="p-3 bg-neutral-50 rounded-lg border border-neutral-100"
              >
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full border bg-primary-50 text-primary-700 border-primary-200">
                        SA utama
                      </span>
                      <p className="text-sm font-medium text-neutral-800 truncate">{utama.name}</p>
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">{utama.email}</p>
                  </div>
                  {bisaKelola && (
                    <button
                      type="button"
                      onClick={() => bukaPanel("ganti")}
                      aria-expanded={panel === "ganti"}
                      disabled={sibuk}
                      className={`${tombolKecil} text-neutral-700 border-neutral-300 hover:bg-neutral-50`}
                    >
                      Ganti SA utama
                    </button>
                  )}
                </div>

                {bisaKelola && panel === "ganti" && (
                  <div className="mt-3 pt-3 border-t border-neutral-200 space-y-3">
                    <div>
                      <label
                        htmlFor="tim-sa-ganti"
                        className="text-xs font-medium text-neutral-600 mb-1 block"
                      >
                        SA utama baru:
                      </label>
                      <select
                        id="tim-sa-ganti"
                        value={pilihan}
                        onChange={(e) => setPilihan(e.target.value)}
                        disabled={sibuk}
                        className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                                   focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                      >
                        <option value="">— Pilih SA —</option>
                        {kandidatUtama.map((sa) => (
                          <option key={sa.id} value={sa.id}>
                            {sa.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-neutral-600 min-h-[44px]">
                      <input
                        type="checkbox"
                        checked={pertahankan}
                        onChange={(e) => setPertahankan(e.target.checked)}
                        disabled={sibuk}
                        aria-label={`Pertahankan ${utama.name} sebagai SA tambahan`}
                      />
                      Pertahankan {utama.name} sebagai SA tambahan
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => gantiUtama(pilihan, pertahankan)}
                        disabled={!pilihan || sibuk}
                        className="flex-1 px-3 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg
                                   hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {sibuk ? "Menyimpan..." : "Simpan SA utama"}
                      </button>
                      <button
                        type="button"
                        onClick={tutupPanel}
                        className="px-3 py-2 text-sm text-neutral-600 border border-neutral-300 rounded-lg hover:bg-neutral-50"
                      >
                        Batal
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ) : (
              <li className="text-sm text-neutral-500 text-center py-2">
                Belum ada SA utama. Tugaskan SA lewat assignment.
              </li>
            )}

            {tambahan.map((sa) => (
              <li
                key={sa.id}
                aria-label={`SA tambahan: ${sa.name}`}
                className="p-3 bg-neutral-50 rounded-lg border border-neutral-100"
              >
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full border bg-neutral-100 text-neutral-600 border-neutral-200">
                        SA tambahan
                      </span>
                      <p className="text-sm font-medium text-neutral-800 truncate">{sa.name}</p>
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">{sa.email}</p>
                  </div>
                  {bisaKelola && (
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => gantiUtama(sa.id, false)}
                        disabled={sibuk}
                        aria-label={`Jadikan ${sa.name} SA utama`}
                        className={`${tombolKecil} text-neutral-700 border-neutral-300 hover:bg-neutral-50`}
                      >
                        Jadikan SA utama
                      </button>
                      <button
                        type="button"
                        onClick={() => lepasSA(sa)}
                        disabled={sibuk}
                        aria-label={`Lepas ${sa.name}`}
                        className={`${tombolKecil} text-red-600 border-red-200 hover:bg-red-50`}
                      >
                        Lepas
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {utama && tambahan.length === 0 && (
            <p className="text-xs text-neutral-500 mt-2">Belum ada SA tambahan.</p>
          )}
          {bisaKelola && utama && (
            <p className="text-xs text-neutral-400 mt-2">Project minimal punya satu SA.</p>
          )}
        </>
      )}
    </section>
  );
}
