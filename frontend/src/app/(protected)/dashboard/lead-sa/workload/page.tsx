"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import useSWR from "swr";
import { LoadError } from "@/components/LoadError";
import { fetcher } from "@/lib/fetcher";
import { isPrivileged } from "@/lib/roles";
import { statusBadgeClass } from "@/lib/status";
import type {
  BebanResponse,
  ButuhAksiResponse,
  JatuhTempoResponse,
  JenisButuhAksi,
  MacetResponse,
} from "@/lib/api/workload";
import { useAuthStore } from "@/store/auth";

/**
 * Workload Lead_SA (spec §2.5): beban SA, due date, project macet, project butuh aksi.
 * Hanya Lead_SA/Admin: user lain melihat pesan akses dan tidak ada request (backend juga 403).
 */

const LABEL_AKSI: Record<JenisButuhAksi, string> = {
  awaiting_assignment: "Menunggu assignment",
  dq_kosong: "DQ Number kosong",
  need_clarification: "Need Clarification",
};

const jam = (n: number) => `${n.toLocaleString("id-ID")} jam`;

function labelDue(hariLagi: number, terlambat: boolean): string {
  if (terlambat) return `Terlambat ${-hariLagi} hari`;
  return hariLagi === 0 ? "Hari ini" : `H-${hariLagi}`;
}

function Penanda({ hariLagi, terlambat }: { hariLagi: number; terlambat: boolean }) {
  const warna = terlambat ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700";
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${warna}`}>
      {labelDue(hariLagi, terlambat)}
    </span>
  );
}

interface BagianProps {
  judul: string;
  isLoading: boolean;
  error: unknown;
  onRetry: () => unknown;
  pesanGagal: string;
  kosong: boolean;
  pesanKosong: string;
  children: ReactNode;
}

function Bagian({ judul, isLoading, error, onRetry, pesanGagal, kosong, pesanKosong, children }: BagianProps) {
  let isi: ReactNode;
  if (error) {
    isi = <LoadError message={pesanGagal} onRetry={onRetry} />;
  } else if (isLoading) {
    isi = (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded bg-neutral-100" />
        ))}
      </div>
    );
  } else if (kosong) {
    isi = <p className="text-sm text-neutral-500">{pesanKosong}</p>;
  } else {
    isi = children;
  }
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <h2 className="mb-3 text-lg font-semibold text-neutral-900">{judul}</h2>
      {isi}
    </section>
  );
}

function TautanProject({ id, nama }: { id: string; nama: string }) {
  return (
    <Link href={`/projects/${id}`} className="font-medium text-primary-700 hover:underline">
      {nama}
    </Link>
  );
}

export default function WorkloadPage() {
  const boleh = isPrivileged(useAuthStore((s) => s.user));
  const kunci = (path: string) => (boleh ? path : null);

  const beban = useSWR<BebanResponse>(kunci("/workload/beban"), fetcher);
  const dueDate = useSWR<JatuhTempoResponse>(kunci("/workload/jatuh-tempo"), fetcher);
  const macet = useSWR<MacetResponse>(kunci("/workload/macet"), fetcher);
  const aksi = useSWR<ButuhAksiResponse>(kunci("/workload/butuh-aksi"), fetcher);

  if (!boleh) {
    return <p className="text-neutral-600">Halaman ini hanya untuk Lead_SA atau Admin.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">Workload SA</h1>
          <p className="mt-1 text-neutral-500">
            Pantau beban SA, due date, project yang macet, dan project yang butuh aksi.
          </p>
        </div>
        <Link href="/dashboard/lead-sa" className="shrink-0 text-sm text-primary-700 hover:underline">
          Kembali ke Dashboard Lead SA
        </Link>
      </div>

      <Bagian
        judul="Beban SA"
        isLoading={beban.isLoading}
        error={beban.error}
        onRetry={beban.mutate}
        pesanGagal="Gagal memuat beban SA."
        kosong={beban.data?.items.length === 0}
        pesanKosong="Belum ada SA terdaftar."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-neutral-500">
              <tr>
                <th className="py-2 pr-4 font-medium">Nama</th>
                <th className="py-2 pr-4 font-medium">Peran</th>
                <th className="py-2 pr-4 font-medium">Project aktif</th>
                <th className="py-2 pr-4 font-medium">Subtask aktif</th>
                <th className="py-2 font-medium">Jam minggu ini</th>
              </tr>
            </thead>
            <tbody>
              {beban.data?.items.map((b) => (
                <tr key={b.user_id} className="border-t border-neutral-100">
                  <td className="py-2 pr-4 font-medium text-neutral-900">{b.name}</td>
                  <td className="py-2 pr-4">{b.role}</td>
                  <td className="py-2 pr-4">{b.project_aktif}</td>
                  <td className="py-2 pr-4">{b.subtask_aktif}</td>
                  <td className="py-2">{jam(b.jam_minggu_ini)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Bagian>

      <Bagian
        judul="Due Date"
        isLoading={dueDate.isLoading}
        error={dueDate.error}
        onRetry={dueDate.mutate}
        pesanGagal="Gagal memuat data due date."
        kosong={dueDate.data?.subtask.length === 0 && dueDate.data?.project.length === 0}
        pesanKosong="Tidak ada subtask atau project yang lewat atau mendekati due date."
      >
        <div className="space-y-4">
          {dueDate.data && dueDate.data.project.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-neutral-700">Project (target submit)</h3>
              <ul className="space-y-2">
                {dueDate.data.project.map((p) => (
                  <li key={p.id_project} className="flex items-center justify-between gap-3 text-sm">
                    <span>
                      <TautanProject id={p.id_project} nama={p.project_name} />
                      <span className="text-neutral-500"> · {p.customer_name} · {p.target_submit}</span>
                    </span>
                    <Penanda hariLagi={p.hari_lagi} terlambat={p.terlambat} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {dueDate.data && dueDate.data.subtask.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-neutral-700">Subtask</h3>
              <ul className="space-y-2">
                {dueDate.data.subtask.map((s) => (
                  <li key={s.id_subtask} className="flex items-center justify-between gap-3 text-sm">
                    <span>
                      <span className="font-medium text-neutral-900">{s.title}</span>
                      <span className="text-neutral-500">
                        {" "}· {s.project_name} · {s.due_date} ·{" "}
                      </span>
                      <span className="text-neutral-500">{s.assigned_sa_name ?? "Belum ditugaskan"}</span>
                    </span>
                    <Penanda hariLagi={s.hari_lagi} terlambat={s.terlambat} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Bagian>

      <Bagian
        judul="Project Macet"
        isLoading={macet.isLoading}
        error={macet.error}
        onRetry={macet.mutate}
        pesanGagal="Gagal memuat project macet."
        kosong={macet.data?.items.length === 0}
        pesanKosong="Tidak ada project yang terlalu lama di satu status."
      >
        <ul className="space-y-2">
          {macet.data?.items.map((p) => (
            <li key={p.id_project} className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <span>
                <TautanProject id={p.id_project} nama={p.project_name} />
                <span className="text-neutral-500"> · {p.customer_name}</span>
              </span>
              <span className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(p.status)}`}>
                  {p.status}
                </span>
                <span className="text-neutral-600">{`${p.hari_di_status} hari (ambang ${p.ambang_hari} hari)`}</span>
              </span>
            </li>
          ))}
        </ul>
      </Bagian>

      <Bagian
        judul="Butuh Aksi"
        isLoading={aksi.isLoading}
        error={aksi.error}
        onRetry={aksi.mutate}
        pesanGagal="Gagal memuat project yang butuh aksi."
        kosong={aksi.data?.items.length === 0}
        pesanKosong="Tidak ada project yang butuh aksi."
      >
        <ul className="space-y-2">
          {aksi.data?.items.map((p) => (
            <li key={`${p.jenis}-${p.id_project}`} className="flex items-center justify-between gap-3 text-sm">
              <span>
                <TautanProject id={p.id_project} nama={p.project_name} />
                <span className="text-neutral-500"> · {p.customer_name}</span>
              </span>
              <span className="shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-700">
                {LABEL_AKSI[p.jenis]}
              </span>
            </li>
          ))}
        </ul>
      </Bagian>
    </div>
  );
}
