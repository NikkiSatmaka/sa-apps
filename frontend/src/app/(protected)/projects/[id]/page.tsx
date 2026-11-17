"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";

import { reprovisionFolder } from "@/lib/api/assignment";
import type { HandoverReadiness } from "@/lib/api/handover";
import { isPrivileged } from "@/lib/roles";
import { useAksesProyek } from "@/lib/useAksesProyek";

import { ProjectDetailContent, type ProjectDetail } from "./project-detail-content";
import { ProjectDetailModals } from "./project-detail-modals";

/**
 * Halaman Detail Proyek
 *
 * Menampilkan informasi lengkap proyek:
 * - Header: nama proyek, customer, status
 * - Info PIC: Sales yang submit, SA yang ditugaskan
 * - Status BANT: passed / not passed (skor dihitung di backend)
 * - Info proyek: DQ Number, target submit, use case tags
 * - Activity logs terkait proyek
 *
 * Requirements: 17.1, 17.6
 */


export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;
  const { user } = useAuthStore();

  // Hak tulis per hubungan (spec §2.0, lib/akses); kontrol tulis disembunyikan bila tidak berhak.
  const { bisa } = useAksesProyek(projectId);
  const [showHandoverModal, setShowHandoverModal] = useState(true);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showReassignModal, setShowReassignModal] = useState(false);
  const [isReprovisioning, setIsReprovisioning] = useState(false);
  const [reprovisionError, setReprovisionError] = useState<string | null>(null);

  // Fetch detail proyek
  const { data: project, error: projError, isLoading, mutate: mutateProject } = useSWR<ProjectDetail>(
    `/projects/${projectId}`,
    fetcher
  );

  // Fetch handover status (hanya jika proyek Won)
  const {
    data: handoverStatus,
    error: handoverError,
    mutate: mutateHandoverStatus,
  } = useSWR<HandoverReadiness>(
    // handover-status ditolak backend (403) bagi yang bukan SA ditugaskan/Lead_SA/Admin.
    project?.status === "Won" && bisa("handover") ? `/projects/${projectId}/handover-status` : null,
    fetcher
  );

  const shouldShowHandoverModal =
    project?.status === "Won" && showHandoverModal && user?.role === "SA" && bisa("handover");

  const shouldShowConfigForm =
    project?.status === "Won" &&
    isPrivileged(user) && // konfigurasi email handover: hanya Lead_SA/Admin (backend)
    handoverStatus &&
    (!handoverStatus.pmo_email || !handoverStatus.delivery_email);


  const handleDeleteProject = async () => {
    if (!project) return;
    setIsDeleting(true);
    try {
      await apiRequest(`/projects/${project.id_project}`, { method: "DELETE" });
      router.push("/");
    } catch {
      alert("Gagal menghapus proyek. Silakan coba lagi.");
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  const handleReprovisionFolder = async () => {
    if (!project || !isPrivileged(user) || project.gdrive_folder_id) return;
    setIsReprovisioning(true);
    setReprovisionError(null);
    try {
      await reprovisionFolder(project.id_project);
      await mutateProject();
    } catch {
      setReprovisionError("Gagal memulai ulang provisioning folder. Silakan coba lagi.");
    } finally {
      setIsReprovisioning(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {isLoading && (
        <div className="space-y-4 animate-pulse">
          <div className="h-8 bg-neutral-200 rounded w-1/3" />
          <div className="h-4 bg-neutral-100 rounded w-1/2" />
          <div className="h-48 bg-neutral-100 rounded" />
        </div>
      )}
      {projError && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-700">Gagal memuat detail proyek. Silakan coba lagi.</p>
        </div>
      )}
      {project && (
        <ProjectDetailContent
          project={project}
          projectId={projectId}
          user={user}
          bisa={bisa}
          router={router}
          onProjectChanged={() => mutateProject()}
          onAssign={() => setShowAssignModal(true)}
          onReassign={() => setShowReassignModal(true)}
          onDelete={() => setShowDeleteConfirm(true)}
          folderProvisioning={{
            isRetrying: isReprovisioning,
            error: reprovisionError,
            onRetry: handleReprovisionFolder,
          }}
          handover={{
            status: handoverStatus,
            error: handoverError,
            onRetry: () => mutateHandoverStatus(),
            onSuccess: () => mutateHandoverStatus(),
            shouldShowConfigForm,
            shouldShowModal: shouldShowHandoverModal,
            onAcknowledge: () => setShowHandoverModal(false),
          }}
        />
      )}
      <ProjectDetailModals
        project={project}
        showAssign={showAssignModal}
        onCloseAssign={() => setShowAssignModal(false)}
        onSuccessAssign={() => {
          setShowAssignModal(false);
          window.location.reload();
        }}
        showReassign={showReassignModal}
        onCloseReassign={() => setShowReassignModal(false)}
        onSuccessReassign={() => {
          setShowReassignModal(false);
          window.location.reload();
        }}
        showDelete={showDeleteConfirm}
        isDeleting={isDeleting}
        onCancelDelete={() => setShowDeleteConfirm(false)}
        onDelete={handleDeleteProject}
      />
    </div>
  );
}

