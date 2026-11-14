"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { statusBadgeClass } from "@/lib/status";
import { LoadError } from "@/components/LoadError";

/**
 * Section "Tugas Saya" di dashboard SA (#126, Tracker-4).
 *
 * Daftar subtask yang ditugaskan ke user login lintas project (GET /subtasks/saya), urut due date
 * dari backend (due date kosong di akhir). Filter status dan opsi menyertakan project Closed/Lost
 * dikirim sebagai query string; default semua status dan tanpa project Closed/Lost.
 */

type StatusSubtask = "open" | "in_progress" | "done";

interface TugasSaya {
  id_subtask: string;
  id_project: string;
  title: string;
  status: StatusSubtask;
  due_date: string | null;
  /** Decimal dari backend sebagai string (mis. "12.50"). */
  estimate_hours: string | null;
  terlambat: boolean;
  project_name: string;
  customer_name: string;
  project_status: string;
}

interface DaftarTugasSaya {
  items: TugasSaya[];
  total: number;
}

const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

const OPSI_STATUS: { nilai: "" | StatusSubtask; label: string }[] = [
  { nilai: "", label: "Semua status" },
  { nilai: "open", label: "Terbuka" },
  { nilai: "in_progress", label: "Dikerjakan" },
  { nilai: "done", label: "Selesai" },
];

/** "2030-01-15" → "15 Jan 2030" (tanpa Date, jadi bebas pergeseran zona waktu). */
function formatTanggal(iso: string): string {
  const [tahun, bulan, hari] = iso.split("-").map(Number);
  return `${hari} ${BULAN[bulan - 1]} ${tahun}`;
}

/** "12.50" → "12,5 jam". */
function formatJam(desimal: string): string {
  return `${String(Number(desimal)).replace(".", ",")} jam`;
}

function badgeStatus(status: StatusSubtask): { label: string; className: string } {
  switch (status) {
    case "done":
      return { label: "Selesai", className: "bg-green-100 text-green-700 border-green-200" };
    case "in_progress":
      return { label: "Dikerjakan", className: "bg-blue-100 text-blue-700 border-blue-200" };
    default:
      return { label: "Terbuka", className: "bg-neutral-100 text-neutral-600 border-neutral-200" };
  }
}

export function TugasSayaSection() {
  const [status, setStatus] = useState<"" | StatusSubtask>("");
  const [sertakanSelesai, setSertakanSelesai] = useState(false);

  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (sertakanSelesai) params.set("sertakan_project_selesai", "true");
  const query = params.toString();

  const { data, error, isLoading, mutate } = useSWR<DaftarTugasSaya>(
    `/subtasks/saya${query ? `?${query}` : ""}`,
    fetcher
  );

  return (
    <section aria-labelledby="tugas-saya-heading">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <h2 id="tugas-saya-heading" className="text-lg font-semibold text-neutral-800">
          Tugas Saya
        </h2>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="tugas-saya-status" className="text-xs font-medium text-neutral-600 mb-1 block">
              Status
            </label>
            <select
              id="tugas-saya-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as "" | StatusSubtask)}
              className="px-2 py-1.5 text-sm border border-neutral-300 rounded-lg bg-white min-h-[36px]"
            >
              {OPSI_STATUS.map((o) => (
                <option key={o.nilai} value={o.nilai}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-neutral-600 min-h-[44px]">
            <input
              type="checkbox"
              checked={sertakanSelesai}
              onChange={(e) => setSertakanSelesai(e.target.checked)}
            />
            Sertakan project Closed/Lost
          </label>
        </div>
      </div>

      {isLoading && (
        <div className="rounded-lg border border-neutral-200 bg-white p-5 space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 bg-neutral-100 rounded animate-pulse" />
          ))}
        </div>
      )}

      {error && !data && <LoadError message="Gagal memuat tugas Anda." onRetry={() => mutate()} />}

      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-neutral-200 bg-white p-8 text-center">
          <p className="text-sm text-neutral-500">Belum ada tugas yang ditugaskan kepada Anda.</p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="rounded-lg border border-neutral-200 bg-white divide-y divide-neutral-100">
          {data.items.map((tugas) => {
            const badge = badgeStatus(tugas.status);
            return (
              <li key={tugas.id_subtask} aria-label={`Tugas ${tugas.title}`} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${badge.className}`}>
                    {badge.label}
                  </span>
                  <p className="text-sm font-medium text-neutral-800">{tugas.title}</p>
                  {tugas.terlambat && (
                    <span className="px-2 py-0.5 text-xs font-medium rounded-full border bg-red-100 text-red-700 border-red-200">
                      Terlambat
                    </span>
                  )}
                </div>
                <p className="text-xs text-neutral-500 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <Link
                    href={`/projects/${tugas.id_project}`}
                    className="font-medium text-primary-600 hover:underline"
                  >
                    {tugas.project_name}
                  </Link>
                  <span>{tugas.customer_name}</span>
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${statusBadgeClass(tugas.project_status)}`}
                  >
                    {tugas.project_status}
                  </span>
                </p>
                <p className="text-xs text-neutral-500 mt-1 flex gap-3 flex-wrap">
                  <span>Jatuh tempo: {tugas.due_date ? formatTanggal(tugas.due_date) : "Belum ditentukan"}</span>
                  {tugas.estimate_hours !== null && <span>Estimasi: {formatJam(tugas.estimate_hours)}</span>}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
