"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { ActivityLogForm } from "@/components/ActivityLogForm";

/**
 * Halaman Activity Log
 *
 * Struktur:
 * - Form input activity log baru
 * - Link ke halaman Calendar Sync
 * - ?project=<id> memilih proyek otomatis
 *
 * Riwayat log ada di /projects/[id]/activity-logs
 *
 * Requirements: 8.1
 */

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

export default function ActivityLogsPage() {
  // useSearchParams butuh Suspense boundary agar build statis tidak gagal
  return (
    <Suspense fallback={null}>
      <ActivityLogsContent />
    </Suspense>
  );
}

function ActivityLogsContent() {
  const searchParams = useSearchParams();
  const defaultProjectId = searchParams.get("project") ?? undefined;
  const { data: rawProjects, isLoading: projectsLoading } = useSWR<ProjectItem[]>(
    "/projects",
    fetcher
  );

  // API mengembalikan id_project; form butuh { id, project_name, status }
  const projects: Project[] = (rawProjects || []).map((p) => ({
    id: p.id_project,
    project_name: p.project_name,
    status: p.status,
  }));

  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="space-y-8 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">Activity Log</h1>
          <p className="mt-1 text-neutral-500 text-sm">
            Catat aktivitas harian Anda pada proyek
          </p>
        </div>
        <div className="flex gap-2">
        {defaultProjectId && (
          <a
            href={`/projects/${defaultProjectId}/activity-logs`}
            className="px-4 py-2.5 text-sm font-medium rounded-lg min-h-[44px] flex items-center
              bg-white border border-neutral-300 text-neutral-700
              hover:bg-neutral-50 transition-colors"
          >
            Riwayat Log Proyek
          </a>
        )}
        <a
          href="/activity-logs/calendar"
          className="px-4 py-2.5 text-sm font-medium rounded-lg min-h-[44px] 
            flex items-center gap-2
            bg-white border border-neutral-300 text-neutral-700 
            hover:bg-neutral-50 transition-colors"
        >
          Calendar Sync
        </a>
        </div>
      </div>

      {/* Form Input Activity Log */}
      <section className="bg-white rounded-xl border border-neutral-200 p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-neutral-800 mb-4">Tambah Activity Log</h2>

        {projectsLoading ? (
          <div className="space-y-3 animate-pulse">
            <div className="h-10 bg-neutral-200 rounded w-full" />
            <div className="h-10 bg-neutral-200 rounded w-full" />
            <div className="h-10 bg-neutral-200 rounded w-1/2" />
            <div className="h-24 bg-neutral-200 rounded w-full" />
          </div>
        ) : (
          <ActivityLogForm
            projects={projects}
            defaultProjectId={defaultProjectId}
            onSuccess={() => setRefreshKey((k) => k + 1)}
          />
        )}
      </section>
    </div>
  );
}
