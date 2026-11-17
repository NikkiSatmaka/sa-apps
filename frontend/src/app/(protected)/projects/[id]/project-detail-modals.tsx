"use client";

import { AssignmentModal } from "@/components/AssignmentModal";
import { ReassignModal } from "@/components/ReassignModal";
import type { ProjectDetail } from "./project-detail-content";

interface Props {
  project?: ProjectDetail;
  showAssign: boolean;
  onCloseAssign: () => void;
  onSuccessAssign: () => void;
  showReassign: boolean;
  onCloseReassign: () => void;
  onSuccessReassign: () => void;
  showDelete: boolean;
  isDeleting: boolean;
  onCancelDelete: () => void;
  onDelete: () => void;
}

export function ProjectDetailModals({
  project,
  showAssign,
  onCloseAssign,
  onSuccessAssign,
  showReassign,
  onCloseReassign,
  onSuccessReassign,
  showDelete,
  isDeleting,
  onCancelDelete,
  onDelete,
}: Props) {
  return (
    <>
      {showAssign && project && (
        <AssignmentModal
          project={{
            id_project: project.id_project,
            project_name: project.project_name,
            customer_name: project.customer_name,
            bant_score: project.bant_score,
            use_case_tags: project.use_case_tags ?? null,
          }}
          onClose={onCloseAssign}
          onSuccess={onSuccessAssign}
        />
      )}
      {showReassign && project && (
        <ReassignModal
          projectId={project.id_project}
          projectName={project.project_name}
          customerName={project.customer_name}
          currentSAName={project.assigned_sa?.name}
          currentLeadSa={
            project.lead_sa?.id
              ? { id: project.lead_sa.id, name: project.lead_sa.name ?? project.lead_sa.id }
              : null
          }
          onClose={onCloseReassign}
          onSuccess={onSuccessReassign}
        />
      )}
      {showDelete && project && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-2 text-lg font-semibold text-neutral-900">Hapus Proyek</h3>
            <p className="mb-4 text-sm text-neutral-600">
              Apakah Anda yakin ingin menghapus proyek{" "}
              <strong>{project.project_name}</strong> ({project.id_project})? Proyek akan hilang dari
              semua daftar dan dashboard. Dokumen dan activity log tetap tersimpan, dan jam kerja SA
              tetap terhitung di utilisasi.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={onCancelDelete}
                disabled={isDeleting}
                className="min-h-[36px] rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={onDelete}
                disabled={isDeleting}
                className="min-h-[36px] rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
              >
                {isDeleting ? "Menghapus..." : "Hapus"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
