"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { ProjectStory } from "@/components/ProjectStory";
import { useAksesProyek } from "@/lib/useAksesProyek";

/**
 * Halaman riwayat Activity Log per proyek (Project Story lengkap).
 *
 * Menampilkan seluruh activity log proyek dengan filter dan pagination.
 * Input log baru tetap di /activity-logs?project=<id>.
 *
 * Requirements: 8.1, 8.5
 */

interface ProjectSummary {
  id_project: string;
  project_name: string;
  customer_name: string;
}

export default function ProjectActivityLogsPage() {
  const params = useParams();
  const projectId = params.id as string;
  // Menulis log = TingkatAkses.TULIS (SA ditugaskan, contributor, Lead_SA, Admin); lainnya hanya membaca
  const bisaMenulis = useAksesProyek(projectId).bisa("tulis");

  const { data: project } = useSWR<ProjectSummary>(`/projects/${projectId}`, fetcher);

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <Link
          href={`/projects/${projectId}`}
          className="text-sm text-primary-600 hover:underline"
        >
          ← Kembali ke proyek
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-neutral-900">Riwayat Activity Log</h1>
            <p className="mt-1 text-sm text-neutral-500">
              {project ? `${project.project_name} — ${project.customer_name}` : projectId}
            </p>
          </div>
          {bisaMenulis && (
            <Link
              href={`/activity-logs?project=${encodeURIComponent(projectId)}`}
              className="px-4 py-2.5 text-sm font-medium rounded-lg min-h-[44px] flex items-center
                bg-primary-600 text-white hover:bg-primary-700 transition-colors"
            >
              + Tambah Log
            </Link>
          )}
        </div>
      </div>

      <ProjectStory projectId={projectId} />
    </div>
  );
}
