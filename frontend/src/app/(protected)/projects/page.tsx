"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import { useAuthStore } from "@/store/auth";
import { ProjectCard } from "@/components/ProjectCard";

/**
 * Halaman /projects — Daftar proyek dengan search dan filter status
 */

interface ProjectItem {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  dq_number: string | null;
  bant_score: number | null;
  use_case_tags: string[];
  target_submit: string | null;
  updated_at: string | null;
}

const ALL_STATUSES = [
  "New",
  "Pending Assignment",
  "Assigned",
  "Ready",
  "Closed-Win",
  "Handover Complete",
  "Need Clarification",
  "Lost",
];

export default function ProjectsPage() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);

  // State untuk search dan filter
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // Tentukan endpoint berdasarkan role
  const getEndpoint = () => {
    if (!user) return null;
    switch (user.role) {
      case "Sales":
        return "/projects?sales_pic=me&sort=-updated_at";
      case "SA":
        return "/projects?assigned_to=me&sort=-updated_at";
      default:
        return "/projects?sort=-updated_at";
    }
  };

  const { data: projects, isLoading, error, mutate } = useSWR<ProjectItem[]>(
    getEndpoint(),
    fetcher
  );

  // Filter client-side berdasarkan search dan status
  const filteredProjects = useMemo(() => {
    if (!projects) return [];
    let result = projects;

    // Filter berdasarkan status
    if (statusFilter) {
      result = result.filter((p) => p.status === statusFilter);
    }

    // Filter berdasarkan search (nama proyek atau customer)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.project_name.toLowerCase().includes(q) ||
          p.customer_name.toLowerCase().includes(q) ||
          (p.id_project && p.id_project.toLowerCase().includes(q))
      );
    }

    return result;
  }, [projects, searchQuery, statusFilter]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">Proyek</h1>
          <p className="mt-1 text-neutral-500 text-sm">
            {user?.role === "Sales"
              ? "Daftar proyek yang Anda submit"
              : user?.role === "SA"
                ? "Proyek yang ditugaskan kepada Anda"
                : "Semua proyek"}
            {/* Catatan: tombol "Request SA" tersedia untuk Sales, SA, dan Lead SA */}
          </p>
        </div>
        {["Sales", "SA", "Lead_SA"].includes(user?.role ?? "") && (
          <button
            onClick={() => router.push("/projects/new")}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600
                       rounded-lg hover:bg-primary-700 transition-colors min-h-[44px]"
          >
            + Request SA
          </button>
        )}
      </div>

      {/* Search + Filter bar */}
      <div className="flex flex-wrap gap-3">
        {/* Search input */}
        <div className="flex-1 min-w-[200px]">
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Cari nama proyek atau customer..."
              className="w-full pl-10 pr-4 py-2.5 border border-neutral-300 rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                placeholder:text-neutral-400"
            />
          </div>
        </div>

        {/* Filter status dropdown */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2.5 border border-neutral-300 rounded-lg text-sm min-w-[180px]
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        >
          <option value="">Semua Status</option>
          {ALL_STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Jumlah hasil */}
      {!isLoading && projects && (
        <p className="text-xs text-neutral-500">
          Menampilkan {filteredProjects.length} dari {projects.length} proyek
        </p>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="rounded-lg border border-neutral-200 bg-white p-4 animate-pulse">
              <div className="h-4 w-36 bg-neutral-200 rounded mb-2" />
              <div className="h-3 w-28 bg-neutral-100 rounded mb-3" />
              <div className="flex justify-between">
                <div className="h-3 w-20 bg-neutral-100 rounded" />
                <div className="h-5 w-20 bg-neutral-200 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      )}

      {error && !projects && (
        <LoadError message="Gagal memuat daftar proyek." onRetry={() => mutate()} />
      )}

      {/* Konten */}
      {!isLoading && projects && (
        <>
          {filteredProjects.length === 0 ? (
            <div className="rounded-lg border border-neutral-200 bg-white p-12 text-center">
              <div className="mx-auto w-16 h-16 rounded-full bg-neutral-100 flex items-center justify-center mb-4">
                <svg className="w-8 h-8 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-neutral-900 mb-2">
                {searchQuery || statusFilter ? "Tidak ada hasil" : "Belum ada proyek"}
              </h3>
              <p className="text-sm text-neutral-500 mb-4">
                {searchQuery || statusFilter
                  ? "Coba ubah kata kunci atau filter status."
                  : ["Sales", "SA", "Lead_SA"].includes(user?.role ?? "")
                    ? "Buat Request SA untuk memulai."
                    : "Belum ada proyek yang tersedia."}
              </p>
              {(searchQuery || statusFilter) && (
                <button
                  onClick={() => { setSearchQuery(""); setStatusFilter(""); }}
                  className="px-4 py-2 text-sm font-medium text-primary-600 border border-primary-200
                             rounded-lg hover:bg-primary-50 transition-colors min-h-[44px]"
                >
                  Reset Filter
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredProjects.map((project) => (
                <ProjectCard
                  key={project.id_project}
                  id={project.id_project}
                  projectName={project.project_name}
                  customerName={project.customer_name}
                  status={project.status}
                  dqNumber={project.dq_number}
                  lastUpdated={project.updated_at || ""}
                  bantScore={project.bant_score}
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
