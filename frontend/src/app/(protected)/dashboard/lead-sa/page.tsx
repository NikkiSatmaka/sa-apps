"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import {
  PendingProject,
  AvailableSA,
  reprovisionFolder,
} from "@/lib/api/assignment";
import { AssignmentModal } from "@/components/AssignmentModal";
import { useAuthStore } from "@/store/auth";
import { isPrivileged } from "@/lib/roles";

/**
 * Dashboard Lead_SA
 *
 * Empat section utama:
 * 1. Antrian Assignment — proyek berstatus "Pending Assignment"
 * 2. Overview Proyek Aktif — count proyek per status
 * 3. Utilisasi SA — daftar SA dengan jumlah proyek aktif
 * 4. Utilisasi SA per Bulan — jam kerja per SA per bulan (chart tabel)
 *
 * Requirements: 4.1, 9.3
 */

/** Tipe ringkasan proyek per status */
interface StatusCount {
  status: string;
  count: number;
}

/** Data utilisasi per SA per bulan */
interface SAMonthlyData {
  sa_id: string;
  sa_name: string;
  months: Record<string, number>;
  total_hours: number;
}

interface UtilizationResponse {
  year: number;
  monthly_data: SAMonthlyData[];
  summary: {
    months: Record<string, number>;
    total_hours: number;
    sa_count: number;
  };
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

/** Nama bulan singkat */
const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

export default function LeadSADashboard() {
  const router = useRouter();
  // State untuk modal assignment
  const [assigningProject, setAssigningProject] =
    useState<PendingProject | null>(null);
  // State untuk toast notification
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);
  // State untuk tahun utilisasi
  const [utilizationYear, setUtilizationYear] = useState<number>(
    new Date().getFullYear()
  );
  // State untuk filter SA individu
  const [selectedSAId, setSelectedSAId] = useState<string>("");

  // Fetch proyek pending assignment
  const {
    data: pendingProjects,
    isLoading: isLoadingPending,
    error: pendingError,
    mutate: mutatePending,
  } = useSWR<PendingProject[]>("/projects/pending-assignment", fetcher);

  // Fetch overview proyek aktif (count per status)
  const {
    data: statusSummary,
    isLoading: isLoadingStatus,
    error: statusError,
    mutate: mutateStatus,
  } = useSWR<StatusCount[]>("/projects/status-summary", fetcher);

  // Fetch utilisasi SA (proyek aktif)
  const {
    data: saUtilization,
    isLoading: isLoadingSA,
    error: saError,
    mutate: mutateSA,
  } = useSWR<AvailableSA[]>("/sa/available", fetcher);

  // Fetch utilisasi SA per bulan
  const utilizationUrl = selectedSAId
    ? `/sa/utilization?year=${utilizationYear}&sa_id=${selectedSAId}`
    : `/sa/utilization?year=${utilizationYear}`;
  const { data: monthlyUtilization, isLoading: isLoadingMonthly, error: monthlyError } =
    useSWR<UtilizationResponse>(utilizationUrl, fetcher, { keepPreviousData: true });

  /**
   * Callback setelah assignment berhasil
   * Refresh data dan tampilkan toast
   */
  const handleAssignmentSuccess = useCallback(() => {
    setAssigningProject(null);
    mutatePending(); // Refresh daftar pending
    setToast({ message: "SA berhasil ditugaskan ke proyek!", type: "success" });

    // Auto-dismiss toast setelah 3 detik (Requirement 19.3)
    setTimeout(() => setToast(null), 3000);
  }, [mutatePending]);

  return (
    <div className="space-y-6">
      {/* Header halaman */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">
            Dashboard Lead SA
          </h1>
          <p className="mt-1 text-neutral-500">
            Kelola assignment proyek dan pantau utilisasi tim SA.
          </p>
        </div>

        {/* Tombol Request SA — Lead SA bisa mengajukan request proyek baru */}
        <button
          onClick={() => router.push("/projects/new")}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600
                     rounded-lg hover:bg-primary-700 transition-colors duration-100
                     min-h-[44px] min-w-[44px] shrink-0"
        >
          + Request SA
        </button>
      </div>

      {/* Toast notification */}
      {toast && (
        <div
          className={`
            fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg
            transition-all duration-200 flex items-center gap-2
            ${
              toast.type === "success"
                ? "bg-green-50 border border-green-200 text-green-700"
                : "bg-red-50 border border-red-200 text-red-700"
            }
          `}
          role="alert"
        >
          {toast.type === "success" ? (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                clipRule="evenodd"
              />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
          )}
          <span className="text-sm font-medium">{toast.message}</span>
          <button
            onClick={() => setToast(null)}
            className="ml-2 text-current opacity-60 hover:opacity-100"
            aria-label="Tutup notifikasi"
          >
            ×
          </button>
        </div>
      )}

      {/* Section 1: Antrian Assignment */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Antrian Assignment
          </h2>
          {pendingProjects && (
            <span className="px-2.5 py-1 bg-yellow-100 text-yellow-700 text-xs font-medium rounded-full">
              {pendingProjects.length} menunggu
            </span>
          )}
        </div>

        {/* Loading skeleton */}
        {isLoadingPending && <PendingListSkeleton />}

        {pendingError && !pendingProjects && (
          <LoadError message="Gagal memuat antrian assignment." onRetry={() => mutatePending()} />
        )}

        {/* Daftar proyek pending */}
        {!isLoadingPending && pendingProjects && (
          <>
            {pendingProjects.length === 0 ? (
              <div className="rounded-lg border border-neutral-200 bg-white p-8 text-center">
                <p className="text-neutral-500 text-sm">
                  Tidak ada proyek yang menunggu assignment saat ini.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {pendingProjects.map((project) => (
                  <ProjectCard
                    key={project.id_project}
                    project={project}
                    onAssign={() => setAssigningProject(project)}
                    onReprovisioned={() => mutatePending()}
                    onToast={(message, type) => {
                      setToast({ message, type });
                      setTimeout(() => setToast(null), 3000);
                    }}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {/* Section 2 & 3: Grid layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Section 2: Overview Proyek Aktif */}
        <section>
          <h2 className="text-lg font-semibold text-neutral-800 mb-4">
            Overview Proyek Aktif
          </h2>

          {isLoadingStatus && <StatusSummarySkeleton />}

          {statusError && !statusSummary && (
            <LoadError message="Gagal memuat ringkasan proyek aktif." onRetry={() => mutateStatus()} />
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
                      Total Aktif
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

        {/* Section 3: Utilisasi SA */}
        <section>
          <h2 className="text-lg font-semibold text-neutral-800 mb-4">
            Utilisasi SA
          </h2>

          {isLoadingSA && <SAUtilizationSkeleton />}

          {saError && !saUtilization && (
            <LoadError message="Gagal memuat utilisasi SA." onRetry={() => mutateSA()} />
          )}

          {!isLoadingSA && saUtilization && (
            <div className="rounded-lg border border-neutral-200 bg-white p-5">
              {saUtilization.length === 0 ? (
                <p className="text-sm text-neutral-500 text-center py-4">
                  Belum ada SA terdaftar.
                </p>
              ) : (
                <div className="space-y-3">
                  {saUtilization.map((sa) => (
                    <div
                      key={sa.id}
                      className="flex items-center gap-3"
                    >
                      {/* Avatar */}
                      <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center shrink-0">
                        {sa.avatar_url ? (
                          <img
                            src={sa.avatar_url}
                            alt={sa.name}
                            className="w-8 h-8 rounded-full object-cover"
                          />
                        ) : (
                          <span className="text-xs font-medium text-primary-600">
                            {sa.name.charAt(0).toUpperCase()}
                          </span>
                        )}
                      </div>

                      {/* Nama */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-neutral-800 truncate">
                          {sa.name}
                        </p>
                      </div>

                      {/* Workload bar + count */}
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="w-16 h-2 bg-neutral-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-200 ${
                              sa.active_project_count <= 2
                                ? "bg-green-400"
                                : sa.active_project_count <= 4
                                  ? "bg-yellow-400"
                                  : "bg-red-400"
                            }`}
                            style={{
                              width: `${Math.min((sa.active_project_count / 6) * 100, 100)}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs font-medium text-neutral-600 w-6 text-right">
                          {sa.active_project_count}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {/* Section 4a: Komposisi Utilisasi (Project vs Non-Project + Fase) */}
      <section>
        <h2 className="text-lg font-semibold text-neutral-800 mb-4">
          Komposisi Utilisasi
        </h2>
        <UtilizationSummarySection
          year={utilizationYear}
          onYearChange={setUtilizationYear}
        />
      </section>

      {/* Section 4: Utilisasi SA per Bulan */}
      <section>
        <h2 className="text-lg font-semibold text-neutral-800 mb-4">
          Utilisasi SA per Bulan (Jam Kerja)
        </h2>

        {isLoadingMonthly && !monthlyUtilization ? (
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="space-y-2 animate-pulse">
              <div className="h-8 bg-neutral-200 rounded w-full" />
              <div className="h-6 bg-neutral-100 rounded w-full" />
              <div className="h-6 bg-neutral-100 rounded w-full" />
              <div className="h-6 bg-neutral-100 rounded w-full" />
            </div>
          </div>
        ) : monthlyError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <p className="text-sm text-red-700">
              Gagal memuat data utilisasi.
              {(monthlyError as { message?: string })?.message && (
                <span className="block mt-1 text-xs text-red-500">
                  {(monthlyError as { message?: string }).message}
                </span>
              )}
            </p>
          </div>
        ) : (
          <MonthlyUtilizationTable
            data={monthlyUtilization}
            year={utilizationYear}
            onYearChange={setUtilizationYear}
            saList={saUtilization}
            selectedSAId={selectedSAId}
            onSAChange={setSelectedSAId}
          />
        )}
      </section>

      {/* Section 5: Utilisasi per Proyek */}
      <section>
        <h2 className="text-lg font-semibold text-neutral-800 mb-4">
          Effort per Proyek
        </h2>
        <ProjectUtilizationSection />
      </section>

      {/* Modal Assignment */}
      {assigningProject && (
        <AssignmentModal
          project={assigningProject}
          onClose={() => setAssigningProject(null)}
          onSuccess={handleAssignmentSuccess}
        />
      )}
    </div>
  );
}

// === Sub-komponen ===

/**
 * Tabel utilisasi SA per bulan
 * Menampilkan jam kerja per SA per bulan dalam format tabel horizontal
 */
function MonthlyUtilizationTable({
  data,
  year,
  onYearChange,
  saList,
  selectedSAId,
  onSAChange,
}: {
  data: UtilizationResponse | undefined;
  year: number;
  onYearChange: (y: number) => void;
  saList: AvailableSA[] | undefined;
  selectedSAId: string;
  onSAChange: (id: string) => void;
}) {
  /** Warna heatmap berdasarkan jam */
  const getHeatmapBg = (hours: number): string => {
    if (hours === 0) return "";
    if (hours < 10) return "bg-blue-50";
    if (hours < 30) return "bg-blue-100";
    if (hours < 60) return "bg-blue-200";
    return "bg-blue-300";
  };

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Pilih tahun */}
        <div className="flex items-center gap-2">
          <label htmlFor="util-year" className="text-xs text-neutral-500">
            Tahun
          </label>
          <select
            id="util-year"
            value={year}
            onChange={(e) => onYearChange(Number(e.target.value))}
            className="px-2 py-1.5 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            {[year - 1, year, year + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>

        {/* Filter per SA */}
        <div className="flex items-center gap-2">
          <label htmlFor="util-sa" className="text-xs text-neutral-500">
            SA
          </label>
          <select
            id="util-sa"
            value={selectedSAId}
            onChange={(e) => onSAChange(e.target.value)}
            className="px-2 py-1.5 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="">Semua SA</option>
            {saList?.map((sa) => (
              <option key={sa.id} value={sa.id}>{sa.name}</option>
            ))}
          </select>
        </div>

        {/* Total ringkasan */}
        {data && (
          <div className="ml-auto text-xs text-neutral-500">
            Total: <span className="font-semibold text-neutral-700">{data.summary.total_hours} jam</span>
            {" "}dari {data.summary.sa_count} SA
          </div>
        )}
      </div>

      {/* Tabel utilisasi */}
      {!data ? (
        <div className="rounded-lg border border-neutral-200 bg-white p-5">
          <div className="space-y-2 animate-pulse">
            <div className="h-8 bg-neutral-200 rounded w-full" />
            <div className="h-6 bg-neutral-100 rounded w-full" />
            <div className="h-6 bg-neutral-100 rounded w-full" />
          </div>
        </div>
      ) : data.monthly_data.length === 0 ? (
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-center">
          <p className="text-sm text-neutral-500">
            Belum ada data activity log untuk tahun {year}.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-neutral-200 bg-white overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-neutral-100">
                <th className="text-left px-3 py-2.5 font-semibold text-neutral-700 whitespace-nowrap sticky left-0 bg-white z-10">
                  SA
                </th>
                {MONTH_LABELS.map((m, idx) => (
                  <th key={idx} className="text-center px-2 py-2.5 font-medium text-neutral-600 min-w-[48px]">
                    {m}
                  </th>
                ))}
                <th className="text-center px-3 py-2.5 font-semibold text-neutral-700 whitespace-nowrap">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {data.monthly_data.map((sa) => (
                <tr key={sa.sa_id} className="border-b border-neutral-50 hover:bg-neutral-50/50">
                  <td className="px-3 py-2 font-medium text-neutral-800 whitespace-nowrap sticky left-0 bg-white z-10">
                    {sa.sa_name}
                  </td>
                  {MONTH_LABELS.map((_, idx) => {
                    const hours = sa.months[String(idx + 1)] || 0;
                    return (
                      <td
                        key={idx}
                        className={`text-center px-2 py-2 ${getHeatmapBg(hours)}`}
                      >
                        {hours > 0 ? (
                          <span className="font-medium text-neutral-700">{hours}</span>
                        ) : (
                          <span className="text-neutral-300">-</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="text-center px-3 py-2 font-semibold text-neutral-900">
                    {sa.total_hours}
                  </td>
                </tr>
              ))}
              {/* Summary row */}
              <tr className="border-t border-neutral-200 bg-neutral-50">
                <td className="px-3 py-2.5 font-semibold text-neutral-700 sticky left-0 bg-neutral-50 z-10">
                  Total
                </td>
                {MONTH_LABELS.map((_, idx) => {
                  const hours = data.summary.months[String(idx + 1)] || 0;
                  return (
                    <td key={idx} className="text-center px-2 py-2.5 font-semibold text-neutral-700">
                      {hours > 0 ? hours : "-"}
                    </td>
                  );
                })}
                <td className="text-center px-3 py-2.5 font-bold text-neutral-900">
                  {data.summary.total_hours}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// === Sub-komponen ===

/**
 * Card proyek dalam antrian assignment
 * Menampilkan detail proyek + tombol Assign + badge Folder Pending
 */
function ProjectCard({
  project,
  onAssign,
  onReprovisioned,
  onToast,
}: {
  project: PendingProject;
  onAssign: () => void;
  onReprovisioned: () => void;
  onToast: (message: string, type: "success" | "error") => void;
}) {
  // Role user untuk gating tombol "Provision Ulang" (Lead_SA/Admin saja)
  const canReprovision = isPrivileged(useAuthStore((s) => s.user));
  const [isReprovisioning, setIsReprovisioning] = useState(false);

  const handleReprovision = async () => {
    setIsReprovisioning(true);
    try {
      await reprovisionFolder(project.id_project);
      onToast("Provisioning folder telah dijadwalkan ulang.", "success");
      onReprovisioned();
    } catch (err) {
      const message =
        (err as { message?: string })?.message ||
        "Gagal menjadwalkan provisioning ulang.";
      onToast(message, "error");
    } finally {
      setIsReprovisioning(false);
    }
  };

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5 hover:shadow-sm transition-shadow duration-200">
      {/* Header card */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 truncate">
            {project.project_name}
          </h3>
          <p className="text-xs text-neutral-500 truncate mt-0.5">
            {project.customer_name}
          </p>
        </div>

        {/* BANT Status badge */}
        <span
          className={`
            shrink-0 px-2.5 py-1 text-xs font-semibold rounded-full
            ${
              project.bant_score >= 60
                ? "bg-green-100 text-green-700"
                : "bg-amber-100 text-amber-700"
            }
          `}
        >
          {project.bant_score >= 60 ? "BANT Passed" : "BANT not passed"}
        </span>
      </div>

      {/* Tags */}
      {project.use_case_tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {project.use_case_tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 bg-neutral-100 text-neutral-600 text-xs rounded"
            >
              {tag}
            </span>
          ))}
          {project.use_case_tags.length > 3 && (
            <span className="px-2 py-0.5 text-neutral-400 text-xs">
              +{project.use_case_tags.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Info tambahan */}
      <div className="flex items-center gap-3 text-xs text-neutral-500 mb-4">
        <span>
          Target: {new Date(project.target_submit).toLocaleDateString("id-ID")}
        </span>
      </div>

      {/* Footer: Badge status provisioning folder + Tombol Assign */}
      <div className="flex items-center justify-between gap-2">
        {/* Badge status provisioning folder — dibaca langsung dari
            folder_provisioning_status (pending/provisioned/failed; null → tanpa badge). */}
        <div className="flex items-center gap-2 min-w-0">
          {project.folder_provisioning_status === "pending" && (
            <span className="px-2.5 py-1 bg-orange-100 text-orange-700 text-xs font-medium rounded-full">
              Folder Pending
            </span>
          )}
          {project.folder_provisioning_status === "provisioned" && (
            <span className="px-2.5 py-1 bg-green-100 text-green-700 text-xs font-medium rounded-full">
              Folder Siap
            </span>
          )}
          {project.folder_provisioning_status === "failed" && (
            <span className="px-2.5 py-1 bg-red-100 text-red-700 text-xs font-medium rounded-full">
              Provisioning Gagal
            </span>
          )}

          {/* Tombol Provision Ulang — hanya saat gagal & role Lead_SA/Admin */}
          {project.folder_provisioning_status === "failed" && canReprovision && (
            <button
              onClick={handleReprovision}
              disabled={isReprovisioning}
              className="px-2.5 py-1 text-xs font-medium text-red-700 border border-red-200
                         rounded-lg hover:bg-red-50 transition-colors duration-100
                         min-h-[36px] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isReprovisioning ? "Memproses…" : "Provision Ulang"}
            </button>
          )}
        </div>

        {/* Tombol Assign */}
        <button
          onClick={onAssign}
          className="shrink-0 px-3 py-1.5 text-xs font-medium text-white bg-primary-600
                     rounded-lg hover:bg-primary-700 transition-colors duration-100
                     min-h-[36px] min-w-[44px]"
        >
          Assign SA
        </button>
      </div>
    </div>
  );
}

// === Loading Skeletons (Requirement 19.5) ===

/** Skeleton untuk daftar proyek pending */
function PendingListSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="rounded-lg border border-neutral-200 bg-white p-5"
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="h-4 w-40 bg-neutral-200 rounded animate-pulse mb-1.5" />
              <div className="h-3 w-28 bg-neutral-100 rounded animate-pulse" />
            </div>
            <div className="h-6 w-16 bg-neutral-200 rounded-full animate-pulse" />
          </div>
          <div className="flex gap-1.5 mb-3">
            <div className="h-5 w-16 bg-neutral-100 rounded animate-pulse" />
            <div className="h-5 w-20 bg-neutral-100 rounded animate-pulse" />
          </div>
          <div className="h-3 w-48 bg-neutral-100 rounded animate-pulse mb-4" />
          <div className="flex justify-end">
            <div className="h-8 w-20 bg-neutral-200 rounded-lg animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Skeleton untuk ringkasan status */
function StatusSummarySkeleton() {
  return (
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
  );
}

/** Skeleton untuk utilisasi SA */
function SAUtilizationSkeleton() {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5">
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-neutral-200 animate-pulse" />
            <div className="flex-1">
              <div className="h-4 w-24 bg-neutral-200 rounded animate-pulse" />
            </div>
            <div className="h-2 w-16 bg-neutral-100 rounded animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}

// === Section: Project Utilization ===

/** Data utilisasi per proyek */
interface ProjectUtilData {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  total_hours: number;
  sa_personnel: { sa_id: string; sa_name: string; hours: number }[];
}

/** Komponen section utilisasi per proyek */
function ProjectUtilizationSection() {
  const router = useRouter();
  const { data, isLoading, error, mutate } = useSWR<ProjectUtilData[]>(
    "/utilization/projects",
    fetcher
  );

  if (isLoading) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="space-y-3 animate-pulse">
          <div className="h-6 bg-neutral-200 rounded w-2/3" />
          <div className="h-5 bg-neutral-100 rounded w-full" />
          <div className="h-5 bg-neutral-100 rounded w-full" />
          <div className="h-5 bg-neutral-100 rounded w-3/4" />
        </div>
      </div>
    );
  }

  if (error && !data) {
    return <LoadError message="Gagal memuat effort per proyek." onRetry={() => mutate()} />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-6 text-center">
        <p className="text-sm text-neutral-500">
          Belum ada data activity log per proyek.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 bg-neutral-50">
              <th className="text-left px-4 py-3 font-semibold text-neutral-700">Proyek</th>
              <th className="text-left px-4 py-3 font-semibold text-neutral-700">Customer</th>
              <th className="text-center px-4 py-3 font-semibold text-neutral-700">Status</th>
              <th className="text-center px-4 py-3 font-semibold text-neutral-700">Total Jam</th>
              <th className="text-left px-4 py-3 font-semibold text-neutral-700">Personel SA</th>
            </tr>
          </thead>
          <tbody>
            {data.map((proj) => (
              <tr
                key={proj.id_project}
                onClick={() => router.push(`/projects/${proj.id_project}`)}
                className="border-b border-neutral-50 hover:bg-neutral-50 cursor-pointer"
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/projects/${proj.id_project}`}
                    onClick={(e) => e.stopPropagation()}
                    className="font-medium text-primary-600 hover:underline text-sm"
                  >
                    {proj.project_name}
                  </Link>
                  <p className="text-xs text-neutral-400">{proj.id_project}</p>
                </td>
                <td className="px-4 py-3 text-neutral-600">{proj.customer_name}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                    STATUS_BADGE_COLORS[proj.status] || "bg-neutral-100 text-neutral-600"
                  }`}>
                    {proj.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-center font-semibold text-neutral-900">
                  {proj.total_hours}
                </td>
                <td className="px-4 py-3">
                  <div className="space-y-1">
                    {proj.sa_personnel.map((sa) => (
                      <div key={sa.sa_id} className="flex items-center gap-2">
                        <span className="text-xs text-neutral-700">{sa.sa_name}</span>
                        <span className="text-xs text-neutral-400">({sa.hours} jam)</span>
                      </div>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// === Section: Komposisi Utilisasi (work_type + fase) ===

interface UtilizationSummaryData {
  year: number;
  work_type: {
    months: Record<string, { Project: number; "Non-Project": number }>;
    totals: { Project: number; "Non-Project": number };
    grand_total: number;
  };
  project_phase: {
    totals: Record<string, number>;
    total: number;
  };
}

const PHASE_LABELS = [
  "Pre-Implementation",
  "Implementation",
  "Post-Implementation",
] as const;

const PHASE_COLORS: Record<string, string> = {
  "Pre-Implementation": "bg-indigo-500",
  Implementation: "bg-amber-500",
  "Post-Implementation": "bg-teal-500",
};

/**
 * Section komposisi utilisasi:
 * - Stacked bar Project vs Non-Project per bulan
 * - Breakdown fase proyek (Pre / Implementation / Post)
 * Chart dibuat manual dengan div + Tailwind (tanpa library).
 */
function UtilizationSummarySection({
  year,
  onYearChange,
}: {
  year: number;
  onYearChange: (y: number) => void;
}) {
  const { data, isLoading, error } = useSWR<UtilizationSummaryData>(
    `/utilization/summary?year=${year}`,
    fetcher,
    { keepPreviousData: true }
  );

  if (isLoading && !data) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="space-y-3 animate-pulse">
          <div className="h-6 bg-neutral-200 rounded w-1/3" />
          <div className="h-40 bg-neutral-100 rounded w-full" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">Gagal memuat komposisi utilisasi.</p>
      </div>
    );
  }

  if (!data) return null;

  // Nilai maksimum bulanan (Project + Non-Project) untuk skala tinggi bar
  const monthlyTotals = MONTH_LABELS.map((_, idx) => {
    const m = data.work_type.months[String(idx + 1)] || { Project: 0, "Non-Project": 0 };
    return m.Project + m["Non-Project"];
  });
  const maxMonthly = Math.max(1, ...monthlyTotals);

  const grand = data.work_type.grand_total || 0;
  const projectTotal = data.work_type.totals.Project || 0;
  const nonProjectTotal = data.work_type.totals["Non-Project"] || 0;

  return (
    <div className="space-y-4">
      {/* Filter tahun + total */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <label htmlFor="comp-year" className="text-xs text-neutral-500">Tahun</label>
          <select
            id="comp-year"
            value={year}
            onChange={(e) => onYearChange(Number(e.target.value))}
            className="px-2 py-1.5 border border-neutral-300 rounded-md text-sm
              focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            {[year - 1, year, year + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
        <div className="ml-auto flex items-center gap-4 text-xs text-neutral-600">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-primary-500 inline-block" />
            Project <span className="font-semibold text-neutral-800">{projectTotal} jam</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-neutral-400 inline-block" />
            Non-Project <span className="font-semibold text-neutral-800">{nonProjectTotal} jam</span>
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Stacked bar Project vs Non-Project per bulan */}
        <div className="lg:col-span-2 rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="text-sm font-medium text-neutral-700 mb-4">
            Project vs Non-Project per Bulan
          </h3>
          {grand === 0 ? (
            <p className="text-sm text-neutral-400 text-center py-8">
              Belum ada data activity log untuk tahun {year}.
            </p>
          ) : (
            <div className="flex items-end justify-between gap-1 h-48">
              {MONTH_LABELS.map((label, idx) => {
                const m = data.work_type.months[String(idx + 1)] || { Project: 0, "Non-Project": 0 };
                const total = m.Project + m["Non-Project"];
                const barHeightPct = (total / maxMonthly) * 100;
                const projPct = total > 0 ? (m.Project / total) * 100 : 0;
                const nonProjPct = total > 0 ? (m["Non-Project"] / total) * 100 : 0;
                return (
                  <div key={idx} className="flex-1 flex flex-col items-center gap-1 h-full justify-end">
                    <div
                      className="w-full max-w-[28px] rounded-t overflow-hidden flex flex-col justify-end"
                      style={{ height: `${barHeightPct}%` }}
                      title={`${label}: Project ${m.Project}j, Non-Project ${m["Non-Project"]}j`}
                    >
                      <div className="bg-primary-500 w-full" style={{ height: `${projPct}%` }} />
                      <div className="bg-neutral-400 w-full" style={{ height: `${nonProjPct}%` }} />
                    </div>
                    <span className="text-[10px] text-neutral-400">{label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Breakdown fase proyek */}
        <div className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="text-sm font-medium text-neutral-700 mb-4">
            Fase Proyek (jam)
          </h3>
          {data.project_phase.total === 0 ? (
            <p className="text-sm text-neutral-400 text-center py-8">
              Belum ada aktivitas Project.
            </p>
          ) : (
            <div className="space-y-3">
              {PHASE_LABELS.map((phase) => {
                const hours = data.project_phase.totals[phase] || 0;
                const pct = data.project_phase.total > 0
                  ? (hours / data.project_phase.total) * 100
                  : 0;
                return (
                  <div key={phase}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-neutral-600">{phase}</span>
                      <span className="text-xs font-semibold text-neutral-800">
                        {hours} jam ({Math.round(pct)}%)
                      </span>
                    </div>
                    <div className="w-full h-2.5 bg-neutral-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${PHASE_COLORS[phase] || "bg-neutral-400"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
              <div className="pt-2 border-t border-neutral-100 flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-600">Total Project</span>
                <span className="text-sm font-bold text-neutral-900">
                  {data.project_phase.total} jam
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
