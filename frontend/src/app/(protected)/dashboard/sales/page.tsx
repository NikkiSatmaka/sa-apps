"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import { ProjectCard } from "@/components/ProjectCard";
import { useAuthStore } from "@/store/auth";

/**
 * Dashboard Sales
 *
 * Menampilkan daftar proyek yang disubmit oleh Sales yang sedang login.
 * Informasi per proyek: nama proyek, nama customer, status, tanggal update terakhir.
 *
 * Fitur:
 * - Loading skeleton (bukan spinner) saat data fetching > 200ms
 * - Empty state dengan CTA ke halaman request baru
 * - Sort by most recently updated
 *
 * Requirements: 9.1, 19.5
 */

/** Tipe project yang dikembalikan dari API */
interface SalesProject {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  dq_number: string | null;
  bant_score: number | null;
  sla_days_elapsed?: number | null;
  sla_is_locked?: boolean;
  updated_at: string;
}

/** Tipe ringkasan proyek per status */
interface StatusCount {
  status: string;
  count: number;
}

/** Warna badge per status proyek */
const STATUS_BADGE_COLORS: Record<string, string> = {
  "Pending Assignment": "bg-yellow-100 text-yellow-700",
  Assigned: "bg-blue-100 text-blue-700",
  Ready: "bg-green-100 text-green-700",
  "Closed-Win": "bg-emerald-100 text-emerald-700",
  "Need Clarification": "bg-orange-100 text-orange-700",
  New: "bg-neutral-100 text-neutral-700",
  Lost: "bg-red-100 text-red-700",
  "Scoring Pending": "bg-purple-100 text-purple-700",
  "Manual Review Required": "bg-pink-100 text-pink-700",
  "Handover Complete": "bg-teal-100 text-teal-700",
};

export default function SalesDashboard() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);

  // Fetch proyek milik Sales saat ini, sorted by updated_at descending
  const { data: projects, isLoading, error: projectsError, mutate: mutateProjects } = useSWR<SalesProject[]>(
    user ? "/projects?sales_pic=me&sort=-updated_at" : null,
    fetcher
  );

  // Fetch ringkasan status proyek milik Sales
  const {
    data: statusSummary,
    isLoading: isLoadingStatus,
    error: statusError,
    mutate: mutateStatus,
  } = useSWR<StatusCount[]>(
    user ? "/projects/status-summary?sales_pic=me" : null,
    fetcher
  );

  return (
    <div className="space-y-6">
      {/* Header halaman */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">
            Dashboard Sales
          </h1>
          <p className="mt-1 text-neutral-500">
            Pantau status proyek yang sudah Anda submit.
          </p>
        </div>

        {/* Tombol Request SA */}
        <button
          onClick={() => router.push("/projects/new")}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600
                     rounded-lg hover:bg-primary-700 transition-colors duration-100
                     min-h-[44px] min-w-[44px]"
        >
          + Request SA
        </button>
      </div>

      {/* Overview Proyek */}
      <section>
        <h2 className="text-lg font-semibold text-neutral-800 mb-4">
          Overview Proyek
        </h2>

        {isLoadingStatus && (
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="h-6 w-28 bg-neutral-200 rounded-full animate-pulse" />
                  <div className="h-6 w-8 bg-neutral-100 rounded animate-pulse" />
                </div>
              ))}
            </div>
          </div>
        )}

        {statusError && !statusSummary && (
          <LoadError message="Gagal memuat ringkasan proyek." onRetry={() => mutateStatus()} />
        )}

        {!isLoadingStatus && statusSummary && (
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            {statusSummary.length === 0 ? (
              <p className="text-sm text-neutral-500 text-center py-4">
                Belum ada data proyek.
              </p>
            ) : (
              <div className="space-y-3">
                {statusSummary.map((item) => (
                  <div
                    key={item.status}
                    className="flex items-center justify-between"
                  >
                    <span
                      className={`
                        px-2.5 py-1 text-xs font-medium rounded-full
                        ${STATUS_BADGE_COLORS[item.status] || "bg-neutral-100 text-neutral-600"}
                      `}
                    >
                      {item.status}
                    </span>
                    <span className="text-lg font-semibold text-neutral-900">
                      {item.count}
                    </span>
                  </div>
                ))}
                {/* Total */}
                <div className="flex items-center justify-between pt-3 border-t border-neutral-100">
                  <span className="text-sm font-medium text-neutral-600">
                    Total
                  </span>
                  <span className="text-lg font-bold text-neutral-900">
                    {statusSummary.reduce((acc, s) => acc + s.count, 0)}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Loading skeleton — ditampilkan saat data belum tersedia (Req 19.5) */}
      {isLoading && <ProjectListSkeleton />}

      {projectsError && !projects && (
        <LoadError message="Gagal memuat daftar proyek." onRetry={() => mutateProjects()} />
      )}

      {/* Konten utama: daftar proyek atau empty state */}
      {!isLoading && projects && (
        <>
          {projects.length === 0 ? (
            <EmptyState onCreateNew={() => router.push("/projects/new")} />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {projects.map((project) => (
                <ProjectCard
                  key={project.id_project}
                  id={project.id_project}
                  projectName={project.project_name}
                  customerName={project.customer_name}
                  status={project.status}
                  dqNumber={project.dq_number}
                  lastUpdated={project.updated_at}
                  bantScore={project.bant_score}
                  slaDaysElapsed={project.sla_days_elapsed}
                  slaIsLocked={project.sla_is_locked}
                  onClick={() => router.push(`/projects/${project.id_project}`)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// === Sub-komponen ===

/**
 * Empty state — ditampilkan ketika Sales belum punya proyek
 */
function EmptyState({ onCreateNew }: { onCreateNew: () => void }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-12 text-center">
      {/* Ikon dokumen */}
      <div className="mx-auto w-16 h-16 rounded-full bg-neutral-100 flex items-center justify-center mb-4">
        <svg
          className="w-8 h-8 text-neutral-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
      </div>

      <h3 className="text-lg font-semibold text-neutral-900 mb-2">
        Belum ada proyek
      </h3>
      <p className="text-sm text-neutral-500 mb-6">
        Anda belum memiliki proyek. Buat request baru untuk memulai.
      </p>

      <button
        onClick={onCreateNew}
        className="px-5 py-2.5 text-sm font-medium text-white bg-primary-600
                   rounded-lg hover:bg-primary-700 transition-colors duration-100
                   min-h-[44px]"
      >
        Request SA
      </button>
    </div>
  );
}

/**
 * Loading skeleton — menyerupai layout card proyek (Requirement 19.5)
 * Menampilkan 4 card skeleton saat data sedang difetch
 */
function ProjectListSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="rounded-lg border border-neutral-200 bg-white p-4"
        >
          {/* Header: judul + badge */}
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="h-4 w-36 bg-neutral-200 rounded animate-pulse" />
            <div className="h-5 w-20 bg-neutral-200 rounded animate-pulse" />
          </div>

          {/* Customer name */}
          <div className="h-3.5 w-28 bg-neutral-100 rounded animate-pulse mb-3" />

          {/* Footer: tanggal + skor */}
          <div className="flex items-center justify-between">
            <div className="h-3 w-24 bg-neutral-100 rounded animate-pulse" />
            <div className="h-3 w-14 bg-neutral-100 rounded animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}
