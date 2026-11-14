"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { izinkan, type HubunganProyek, type TingkatAkses } from "@/lib/akses";
import { isPrivileged } from "@/lib/roles";
import { useAuthStore } from "@/store/auth";

interface Orang {
  id: string | null;
}

/** Bagian detail proyek (`GET /projects/{id}`) yang menentukan hubungan pengguna. */
interface ProyekHubungan {
  sales_pic?: Orang | null;
  product_pic?: Orang | null;
  assigned_sa?: Orang | null;
  collaborators?: { user_id: string; role?: string | null }[];
}

interface TimSA {
  sa_utama: { id: string } | null;
  sa_tambahan: { id: string }[];
}

/**
 * Hak tulis pengguna saat ini pada satu proyek, dari data yang sudah dimuat halaman: detail
 * proyek (PIC, SA utama, collaborator) dan `/tim-sa` (SA tambahan). Kunci SWR sama dengan yang
 * dipakai halaman, jadi tidak menambah request. `/tim-sa` hanya diambil untuk SA non-privileged
 * (peran lain tidak bisa menjadi SA tambahan).
 *
 * Selama data belum ada, kontrol disembunyikan; bila `/tim-sa` gagal dimuat, SA tidak
 * disembunyikan (opsi konservatif, backend yang menolak). Bukan penentu hak.
 */
export function useAksesProyek(projectId: string) {
  const user = useAuthStore((s) => s.user);
  const { data: proyek, error: proyekError } = useSWR<ProyekHubungan>(`/projects/${projectId}`, fetcher);
  const perluTim = !!user && !isPrivileged(user) && user.role === "SA";
  const { data: tim, error: timError } = useSWR<TimSA>(perluTim ? `/projects/${projectId}/tim-sa` : null, fetcher);

  const saUtama = proyek?.assigned_sa?.id;
  const hubungan: HubunganProyek = {
    actor: user,
    salesPicId: proyek?.sales_pic?.id,
    productPicId: proyek?.product_pic?.id,
    saIds: tim ? [saUtama, tim.sa_utama?.id, ...tim.sa_tambahan.map((s) => s.id)] : timError ? null : [saUtama],
    kolaborator: proyek?.collaborators,
  };

  // Hubungan belum bisa dinilai: detail proyek (atau tim SA yang dibutuhkan) belum tiba dan belum gagal.
  const memuat = (!proyek && !proyekError) || (perluTim && !tim && !timError);

  return { bisa: (tingkat: TingkatAkses) => izinkan(tingkat, hubungan), memuat };
}
