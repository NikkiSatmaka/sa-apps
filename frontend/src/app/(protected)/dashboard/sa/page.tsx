"use client";

import { statusBadgeClass } from "@/lib/status";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import { SLABadge } from "@/components/SLABadge";
import { TugasSayaSection } from "@/components/TugasSayaSection";

/**
 * Dashboard SA (Solutions Architect)
 *
 * Menampilkan daftar proyek yang ditugaskan ke SA yang sedang login:
 * - Nama proyek, nama customer, status
 * - Progres dokumen: rasio dokumen Final / total dokumen
 * - SLA badge jika DQ Number belum diinput
 * - Quick links ke Activity Log dan Documents
 * - Diurutkan berdasarkan tanggal update terbaru
 *
 * Requirements: 9.2
 */

/** Tipe proyek dari backend (endpoint GET /api/v1/projects untuk SA) */
interface SAProject {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  dq_number: string | null;
  updated_at: string;
  /** Jumlah dokumen berstatus Final */
  doc_final_count: number;
  /** Total dokumen proyek */
  doc_total_count: number;
  /** SLA days elapsed (null jika tidak aktif) */
  sla_days_elapsed: number | null;
  /** Apakah folder Solutions terkunci */
  sla_is_locked: boolean;
}

/** Format tanggal ke format lokal Indonesia */
function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

/** Tipe ringkasan proyek per status */
interface StatusCount {
  status: string;
  count: number;
}

export default function SADashboard() {
  const router = useRouter();

  // Fetch proyek yang ditugaskan ke SA yang login
  const { data: projects, isLoading, error: projectsError, mutate: mutateProjects } = useSWR<SAProject[]>(
    "/projects?assigned_to=me&sort=-updated_at",
    fetcher
  );

  // Fetch ringkasan status proyek SA
  const {
    data: statusSummary,
    isLoading: isLoadingStatus,
    error: statusError,
    mutate: mutateStatus,
  } = useSWR<StatusCount[]>(
    "/projects/status-summary?assigned_to=me",
    fetcher
  );

  return (
    <div className="space-y-6">
      {/* Header halaman */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">
            Dashboard SA
          </h1>
          <p className="mt-1 text-neutral-500">
            Daftar proyek yang ditugaskan kepada Anda.
          </p>
        </div>

        {/* Tombol Request SA — SA bisa mengajukan request proyek baru */}
        <button
          onClick={() => router.push("/projects/new")}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600
                     rounded-lg hover:bg-primary-700 transition-colors duration-100
                     min-h-[44px] min-w-[44px] shrink-0"
        >
          + Request SA
        </button>
      </div>

      {/* Tugas Saya: subtask milik SA lintas project (#126) */}
      <TugasSayaSection />

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
                        ${statusBadgeClass(item.status)}
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

      {/* Loading skeleton (Requirement 19.5) */}
      {isLoading && <ProjectListSkeleton />}

      {projectsError && !projects && (
        <LoadError message="Gagal memuat daftar proyek." onRetry={() => mutateProjects()} />
      )}

      {/* Empty state */}
      {!isLoading && projects && projects.length === 0 && (
        <div className="rounded-lg border border-neutral-200 bg-white p-12 text-center">
          <div className="mx-auto w-12 h-12 rounded-full bg-neutral-100 flex items-center justify-center mb-4">
            <svg
              className="w-6 h-6 text-neutral-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </div>
          <p className="text-neutral-500 text-sm">
            Belum ada proyek yang ditugaskan kepada Anda.
          </p>
        </div>
      )}

      {/* Daftar proyek */}
      {!isLoading && projects && projects.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {projects.map((project) => (
            <SAProjectCard
              key={project.id_project}
              project={project}
              onNavigate={(path) => router.push(path)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// === Sub-komponen ===

/**
 * Card proyek untuk dashboard SA
 * Menampilkan info proyek + progres dokumen + quick links
 */
function SAProjectCard({
  project,
  onNavigate,
}: {
  project: SAProject;
  onNavigate: (path: string) => void;
}) {
  // Hitung rasio dokumen Final / total
  const docProgress =
    project.doc_total_count > 0
      ? `${project.doc_final_count}/${project.doc_total_count} Final`
      : "Belum ada dokumen";

  // Persentase progres untuk progress bar
  const progressPercent =
    project.doc_total_count > 0
      ? (project.doc_final_count / project.doc_total_count) * 100
      : 0;

  return (
    <article
      className="rounded-lg border border-neutral-200 bg-white p-5 hover:shadow-md
                 hover:border-primary-200 transition-all duration-200"
      aria-label={`Proyek ${project.project_name} - ${project.customer_name}`}
    >
      {/* Header: Nama proyek + badges */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <h3
            className="text-sm font-semibold text-neutral-900 line-clamp-2 cursor-pointer hover:text-primary-600"
            onClick={() => onNavigate(`/projects/${project.id_project}`)}
          >
            {project.project_name}
          </h3>
          <p className="text-sm text-neutral-500 mt-0.5 truncate">
            {project.customer_name}
          </p>
        </div>

        <div className="flex flex-col items-end gap-1 shrink-0">
          {/* Badge Status */}
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${statusBadgeClass(project.status)}`}
          >
            {project.status}
          </span>

          {/* Badge "Menunggu DQ" */}
          {project.dq_number === null && (
            <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 whitespace-nowrap">
              Menunggu DQ
            </span>
          )}

          {/* SLA Badge — ditampilkan jika DQ belum diinput dan SLA aktif */}
          {project.sla_days_elapsed != null && project.dq_number === null && (
            <SLABadge
              daysElapsed={project.sla_days_elapsed}
              isLocked={project.sla_is_locked}
            />
          )}
        </div>
      </div>

      {/* Progres dokumen */}
      <div className="mt-3 mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-neutral-600">
            Progres Dokumen
          </span>
          <span className="text-xs font-semibold text-neutral-800">
            {docProgress}
          </span>
        </div>
        {/* Progress bar */}
        <div className="w-full h-2 bg-neutral-100 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              progressPercent === 100
                ? "bg-emerald-500"
                : progressPercent > 0
                  ? "bg-blue-500"
                  : "bg-neutral-200"
            }`}
            style={{ width: `${progressPercent}%` }}
            role="progressbar"
            aria-valuenow={project.doc_final_count}
            aria-valuemin={0}
            aria-valuemax={project.doc_total_count}
            aria-label={`Progres dokumen: ${docProgress}`}
          />
        </div>
      </div>

      {/* Footer: tanggal update + quick links */}
      <div className="flex items-center justify-between pt-3 border-t border-neutral-100">
        <span className="text-xs text-neutral-400">
          Update: {formatDate(project.updated_at)}
        </span>

        {/* Quick links */}
        <div className="flex items-center gap-2">
          <button
            onClick={() =>
              onNavigate(`/activity-logs?project=${project.id_project}`)
            }
            className="px-2.5 py-1 text-xs font-medium text-primary-600 bg-primary-50
                       rounded hover:bg-primary-100 transition-colors duration-100
                       min-h-[32px] min-w-[44px]"
            aria-label={`Activity Log proyek ${project.project_name}`}
          >
            Activity Log
          </button>
          <button
            onClick={() =>
              onNavigate(`/projects/${project.id_project}/documents`)
            }
            className="px-2.5 py-1 text-xs font-medium text-primary-600 bg-primary-50
                       rounded hover:bg-primary-100 transition-colors duration-100
                       min-h-[32px] min-w-[44px]"
            aria-label={`Documents proyek ${project.project_name}`}
          >
            Documents
          </button>
        </div>
      </div>
    </article>
  );
}

// === Loading Skeleton (Requirement 19.5) ===

/** Skeleton loading untuk daftar proyek SA */
function ProjectListSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="rounded-lg border border-neutral-200 bg-white p-5"
        >
          {/* Header skeleton */}
          <div className="flex items-start justify-between mb-2">
            <div className="flex-1">
              <div className="h-4 w-3/4 bg-neutral-200 rounded animate-pulse mb-1.5" />
              <div className="h-3 w-1/2 bg-neutral-100 rounded animate-pulse" />
            </div>
            <div className="h-6 w-16 bg-neutral-200 rounded animate-pulse" />
          </div>

          {/* Progres skeleton */}
          <div className="mt-3 mb-4">
            <div className="flex items-center justify-between mb-1.5">
              <div className="h-3 w-24 bg-neutral-100 rounded animate-pulse" />
              <div className="h-3 w-16 bg-neutral-100 rounded animate-pulse" />
            </div>
            <div className="h-2 w-full bg-neutral-100 rounded-full animate-pulse" />
          </div>

          {/* Footer skeleton */}
          <div className="flex items-center justify-between pt-3 border-t border-neutral-100">
            <div className="h-3 w-28 bg-neutral-100 rounded animate-pulse" />
            <div className="flex gap-2">
              <div className="h-7 w-20 bg-neutral-100 rounded animate-pulse" />
              <div className="h-7 w-20 bg-neutral-100 rounded animate-pulse" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
