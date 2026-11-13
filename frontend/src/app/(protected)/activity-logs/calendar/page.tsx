"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import { CalendarSync } from "@/components/CalendarSync";

/**
 * Halaman Calendar Sync
 *
 * Panel untuk:
 * - Sinkronisasi Google Calendar events (tampilan kalender bulanan)
 * - Mapping events ke subtask + proyek terkait
 *
 * Requirements: 13.1, 13.2
 */

/** Bentuk item dari API /projects (field id_project) */
interface ProjectItem {
  id_project: string;
  project_name: string;
  status?: string;
}

interface Project {
  id: string;
  project_name: string;
  status?: string;
}

export default function CalendarSyncPage() {
  // Fetch daftar proyek untuk mapping dropdown
  const {
    data: rawProjects,
    isLoading: projectsLoading,
    error: projectsError,
    mutate: mutateProjects,
  } = useSWR<ProjectItem[]>(
    "/projects",
    fetcher
  );

  // Normalisasi: API mengembalikan id_project, komponen butuh { id, project_name }
  const projects: Project[] = (rawProjects || []).map((p) => ({
    id: p.id_project,
    project_name: p.project_name,
    status: p.status,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">Calendar Sync</h1>
          <p className="mt-1 text-neutral-500 text-sm">
            Sinkronisasi Google Calendar dan mapping aktivitas ke subtask + proyek
          </p>
        </div>
        {/* Link kembali ke Activity Log */}
        <a
          href="/activity-logs"
          className="px-4 py-2.5 text-sm font-medium rounded-lg min-h-[44px]
            flex items-center gap-2
            bg-white border border-neutral-300 text-neutral-700
            hover:bg-neutral-50 transition-colors"
        >
          ← Activity Log
        </a>
      </div>

      {/* Calendar Sync Panel */}
      <section className="bg-white rounded-xl border border-neutral-200 p-4 sm:p-6 shadow-sm">
        {projectsLoading ? (
          <div className="space-y-3 animate-pulse">
            <div className="h-10 bg-neutral-200 rounded w-full" />
            <div className="h-80 bg-neutral-200 rounded w-full" />
          </div>
        ) : projectsError && !rawProjects ? (
          <LoadError message="Gagal memuat daftar proyek." onRetry={() => mutateProjects()} />
        ) : (
          <CalendarSync projects={projects} />
        )}
      </section>
    </div>
  );
}
