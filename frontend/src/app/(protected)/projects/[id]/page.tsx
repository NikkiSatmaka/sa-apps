"use client";

import { useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { HandoverModal } from "@/components/HandoverModal";
import { HandoverConfigForm } from "@/components/HandoverConfigForm";
import { AssignmentModal } from "@/components/AssignmentModal";
import { ReassignModal } from "@/components/ReassignModal";
import { CollaboratorSection } from "@/components/CollaboratorSection";
import { SubtaskSection } from "@/components/SubtaskSection";
import { QualificationSection } from "@/components/QualificationSection";
import type { QualificationView } from "@/lib/qualification";
import { BANTOverride } from "@/components/BANTOverride";
import { SourceDocumentSection, type SourceDocumentItem } from "@/components/SourceDocumentSection";
import type { HandoverStatus } from "@/lib/api/handover";

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

interface ProjectDetail {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  dq_number: string | null;
  bant_score: number | null;
  bant_detail: {
    budget_mrr?: number | null;
    pic_name?: string | null;
    pic_position?: string | null;
    pic_email?: string | null;
    need_description?: string | null;
    timeline_target?: string | null;
    [key: string]: unknown;
  } | null;
  qualification?: QualificationView;
  use_case_tags: string[];
  target_submit: string | null;
  sales_pic: { id: string | null; name: string | null; email: string | null };
  assigned_sa: { id: string | null; name: string | null; email: string | null } | null;
  collaborators: {
    id: string;
    user_id: string;
    user_name: string;
    user_email: string;
    user_role: string;
    role: "viewer" | "contributor";
    added_by_name: string;
    created_at: string;
  }[];
  source_documents?: SourceDocumentItem[];
  gdrive_folder_id: string | null;
  folder_provisioning_status: "pending" | "provisioned" | "failed" | null;
  created_at: string;
  updated_at: string;
}

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;
  const { user } = useAuthStore();

  const [showHandoverModal, setShowHandoverModal] = useState(true);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showReassignModal, setShowReassignModal] = useState(false);

  // Fetch detail proyek
  const { data: project, error: projError, isLoading } = useSWR<ProjectDetail>(
    `/projects/${projectId}`,
    fetcher
  );

  // Fetch handover status (hanya jika proyek Closed-Win)
  const { data: handoverStatus, mutate: mutateHandoverStatus } = useSWR<HandoverStatus>(
    project?.status === "Closed-Win" ? `/projects/${projectId}/handover-status` : null,
    fetcher
  );

  const shouldShowHandoverModal =
    project?.status === "Closed-Win" && showHandoverModal && user?.role === "SA";

  const shouldShowConfigForm =
    project?.status === "Closed-Win" &&
    handoverStatus &&
    (!handoverStatus.pmo_email || !handoverStatus.delivery_email);

  const canDelete = user?.role === "Lead_SA" || user?.role === "Admin";

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

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Loading */}
      {isLoading && (
        <div className="space-y-4 animate-pulse">
          <div className="h-8 bg-neutral-200 rounded w-1/3" />
          <div className="h-4 bg-neutral-100 rounded w-1/2" />
          <div className="h-48 bg-neutral-100 rounded" />
        </div>
      )}

      {/* Error */}
      {projError && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-700">Gagal memuat detail proyek. Silakan coba lagi.</p>
        </div>
      )}

      {/* Konten */}
      {project && (
        <>
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-neutral-900">
                {project.project_name}
              </h1>
              <p className="text-sm text-neutral-500 mt-1">{project.customer_name}</p>
              <p className="text-xs text-neutral-400 mt-0.5 font-mono">{project.id_project}</p>
              <p className="text-xs text-neutral-400 mt-0.5">
                Terakhir Diubah: {new Date(project.updated_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {/* Tombol Assign SA — hanya Lead_SA/Admin dan status Pending Assignment */}
              {project.status === "Pending Assignment" &&
                (user?.role === "Lead_SA" || user?.role === "Admin") && (
                <button
                  onClick={() => setShowAssignModal(true)}
                  className="px-3 py-1.5 text-sm font-medium text-white bg-primary-600
                             rounded-lg hover:bg-primary-700 transition-colors min-h-[36px]"
                >
                  Assign SA
                </button>
              )}
              {/* Override skor BANT — hanya Lead_SA/Admin pada status relevan (#30) */}
              <BANTOverride
                projectId={project.id_project}
                status={project.status}
                role={user?.role}
                currentScores={project.bant_detail}
              />
              {/* Tombol Reassign SA — hanya Lead_SA/Admin dan proyek sudah punya SA */}
              {project.assigned_sa &&
                ["Assigned", "Ready", "Pending Assignment"].includes(project.status) &&
                (user?.role === "Lead_SA" || user?.role === "Admin") && (
                <button
                  onClick={() => setShowReassignModal(true)}
                  className="px-3 py-1.5 text-sm font-medium text-amber-700 border border-amber-300
                             rounded-lg hover:bg-amber-50 transition-colors min-h-[36px]"
                >
                  Reassign SA
                </button>
              )}
              {/* Tombol Edit */}
              <button
                onClick={() => router.push(`/projects/${projectId}/edit`)}
                className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                           rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px]"
              >
                Edit
              </button>
              {/* Tombol Hapus — hanya Lead_SA/Admin */}
              {canDelete && (
                <button
                  onClick={() => setShowDeleteConfirm(true)}
                  className="px-3 py-1.5 text-sm font-medium text-red-600 border border-red-300
                             rounded-lg hover:bg-red-50 transition-colors min-h-[36px]"
                >
                  Hapus
                </button>
              )}
              <span
                className={`inline-block px-3 py-1 rounded-full text-xs font-medium shrink-0 ${
                  project.status === "Closed-Win" ? "bg-green-100 text-green-700"
                  : project.status === "Lost" ? "bg-red-100 text-red-700"
                  : project.status === "Ready" ? "bg-emerald-100 text-emerald-700"
                  : project.status === "Assigned" ? "bg-blue-100 text-blue-700"
                  : project.status === "Pending Assignment" ? "bg-yellow-100 text-yellow-700"
                  : "bg-neutral-100 text-neutral-700"
                }`}
              >
                {project.status}
              </span>
            </div>
          </div>

          {/* Section: PIC & Info Utama */}
          <div className="bg-white border border-neutral-200 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-neutral-700 mb-3">Informasi Proyek</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <InfoRow label="Sales PIC" value={project.sales_pic?.name || "—"} />
              <InfoRow label="SA Ditugaskan" value={project.assigned_sa?.name || "Belum di-assign"} />
              <InfoRow label="DQ Number" value={project.dq_number || "Belum diinput"} mono={!!project.dq_number} />
              <InfoRow
                label="Target Submit"
                value={project.target_submit
                  ? new Date(project.target_submit).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })
                  : "—"}
              />
              <InfoRow
                label="Dibuat"
                value={new Date(project.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}
              />
            </div>

            {/* Use case tags */}
            {project.use_case_tags.length > 0 && (
              <div className="mt-4 pt-4 border-t border-neutral-100">
                <span className="text-xs text-neutral-500">Use Case Tags:</span>
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {project.use_case_tags.map((tag) => (
                    <span key={tag} className="px-2 py-0.5 bg-primary-50 text-primary-600 text-xs rounded-full">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Section: Quick Actions — icon + text style sederhana */}
          <div className="flex gap-4">
            <a
              href={`/projects/${projectId}/documents`}
              className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-neutral-700
                         border border-neutral-200 rounded-lg hover:bg-neutral-50 transition-colors min-h-[44px]"
            >
              <svg className="w-4 h-4 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Dokumen
            </a>
            <a
              href={`/projects/${projectId}/activity-logs`}
              className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-neutral-700
                         border border-neutral-200 rounded-lg hover:bg-neutral-50 transition-colors min-h-[44px]"
            >
              <svg className="w-4 h-4 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
              </svg>
              Riwayat Log
            </a>
          </div>

          {/* Section: Status BANT — hanya tampilkan pass/fail, skor dihitung di backend */}
          {project.bant_score !== null && project.bant_score !== undefined && (
            <div
              className={`rounded-lg p-4 border ${
                project.bant_score >= 60
                  ? "bg-green-50 border-green-200"
                  : "bg-amber-50 border-amber-200"
              }`}
            >
              <div className="flex items-center gap-2">
                {project.bant_score >= 60 ? (
                  <svg className="w-5 h-5 text-green-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5 text-amber-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                )}
                <p
                  className={`text-sm font-medium ${
                    project.bant_score >= 60 ? "text-green-700" : "text-amber-700"
                  }`}
                >
                  {project.bant_score >= 60
                    ? "BANT Passed, waiting for assignment"
                    : "BANT not passed, please refine your input"}
                </p>
              </div>
            </div>
          )}

          {/* Section: Kualifikasi — jawaban kuesioner + sub-skor, atau data legacy */}
          <QualificationSection
            qualification={project.qualification}
            targetSubmit={project.target_submit}
          />

          <SourceDocumentSection documents={project.source_documents ?? []} />

          {/* Section: Activity Log Proyek */}
          <ProjectActivitySection projectId={projectId} />

          {/* Section: Subtask — work item assignable per proyek */}
          <SubtaskSection projectId={projectId} />

          {/* Section: Kolaborator */}
          <CollaboratorSection
            projectId={projectId}
            initialCollaborators={project.collaborators}
          />

          {/* Section: Konfigurasi Handover */}
          {shouldShowConfigForm && (
            <div className="bg-white border border-amber-200 rounded-lg p-5">
              <h2 className="text-base font-semibold text-neutral-800 mb-3">Konfigurasi Handover</h2>
              <p className="text-sm text-neutral-600 mb-4">
                Email PMO Lead dan Delivery Lead belum dikonfigurasi.
              </p>
              <HandoverConfigForm
                projectId={projectId}
                existingPmoEmail={handoverStatus?.pmo_email}
                existingDeliveryEmail={handoverStatus?.delivery_email}
                onSuccess={() => mutateHandoverStatus()}
              />
            </div>
          )}
        </>
      )}

      {/* Modal Assignment SA */}
      {showAssignModal && project && (
        <AssignmentModal
          project={{
            id_project: project.id_project,
            project_name: project.project_name,
            customer_name: project.customer_name,
            bant_score: project.bant_score || 0,
            use_case_tags: project.use_case_tags || [],
            status: project.status,
            target_submit: project.target_submit || "",
            gdrive_folder_id: null,
            folder_provisioning_status: project.folder_provisioning_status ?? null,
            created_at: project.created_at,
            sales_pic: { id: project.sales_pic?.id || "", name: project.sales_pic?.name || "", email: project.sales_pic?.email || "" },
          }}
          onClose={() => setShowAssignModal(false)}
          onSuccess={() => {
            setShowAssignModal(false);
            window.location.reload();
          }}
        />
      )}

      {/* Modal Reassign SA */}
      {showReassignModal && project && (
        <ReassignModal
          projectId={project.id_project}
          projectName={project.project_name}
          customerName={project.customer_name}
          currentSAName={project.assigned_sa?.name}
          onClose={() => setShowReassignModal(false)}
          onSuccess={() => {
            setShowReassignModal(false);
            window.location.reload();
          }}
        />
      )}

      {/* Modal konfirmasi hapus proyek */}
      {showDeleteConfirm && project && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-neutral-900 mb-2">Hapus Proyek</h3>
            <p className="text-sm text-neutral-600 mb-4">
              Apakah Anda yakin ingin menghapus proyek <strong>{project.project_name}</strong> ({project.id_project})? Proyek akan hilang dari semua daftar dan dashboard. Dokumen dan activity log tetap tersimpan, dan jam kerja SA tetap terhitung di utilisasi.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={isDeleting}
                className="px-3 py-1.5 text-sm font-medium text-neutral-700 border border-neutral-300
                           rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px]
                           disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={handleDeleteProject}
                disabled={isDeleting}
                className="px-3 py-1.5 text-sm font-medium text-white bg-red-600
                           rounded-lg hover:bg-red-700 transition-colors min-h-[36px]
                           disabled:opacity-50"
              >
                {isDeleting ? "Menghapus..." : "Hapus"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Closed-Win */}
      {shouldShowHandoverModal && project && (
        <HandoverModal
          projectId={projectId}
          projectName={project.project_name}
          onAcknowledge={() => setShowHandoverModal(false)}
        />
      )}
    </div>
  );
}

// === Sub-komponen ===

function InfoRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  const isBelum = value.startsWith("Belum");
  return (
    <div>
      <span className="text-neutral-500">{label}:</span>
      <span className={`ml-2 font-medium ${
        isBelum ? "text-red-600 font-bold" : mono ? "font-mono text-sm text-neutral-800" : "text-neutral-800"
      }`}>
        {value}
      </span>
    </div>
  );
}

/** Section: Activity Log ringkasan per proyek + tombol Summarize */
function ProjectActivitySection({ projectId }: { projectId: string }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [isSummarizing, setIsSummarizing] = useState(false);

  const { data, isLoading } = useSWR<{
    items: {
      id_log: string;
      subtask_category: string;
      duration_hours: number;
      raw_notes: string;
      ai_polished_notes?: {
        discussion_points: string[];
        action_items: { description: string; pic?: string | null }[];
      } | null;
      created_at: string;
    }[];
    total: number;
  }>(`/projects/${projectId}/story?page=1&page_size=5`, fetcher);

  // Generate summary dari activity logs menggunakan LLM (backend)
  const handleSummarize = async () => {
    if (!data || data.items.length === 0) return;
    setIsSummarizing(true);
    setSummary(null);

    try {
      const result = await apiRequest<{
        summary: string;
        total_activities: number;
        total_hours: number;
      }>(`/projects/${projectId}/summarize`, { method: "POST" });
      setSummary(result.summary);
    } catch (err) {
      console.error("Summarize failed:", err);
      setSummary(
        "Gagal menghasilkan ringkasan. Silakan coba lagi."
      );
    } finally {
      setIsSummarizing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white border border-neutral-200 rounded-lg p-5">
        <div className="h-5 bg-neutral-200 rounded w-1/4 mb-4 animate-pulse" />
        <div className="space-y-3 animate-pulse">
          <div className="h-10 bg-neutral-100 rounded" />
          <div className="h-10 bg-neutral-100 rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-neutral-700">Project Story</h2>
          {data && data.total > 0 && (
            <p className="text-xs text-neutral-400 mt-0.5">
              {data.total} aktivitas — menampilkan 5 terbaru
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {data && data.total > 0 && (
            <button
              onClick={handleSummarize}
              disabled={isSummarizing}
              className="px-3 py-1.5 text-xs font-medium text-primary-600 border border-primary-200
                         rounded-lg hover:bg-primary-50 transition-colors min-h-[36px]
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSummarizing ? "Generating..." : "Summarize"}
            </button>
          )}
          {data && data.total > 5 && (
            <a
              href={`/projects/${projectId}/activity-logs`}
              className="px-3 py-1.5 text-xs font-medium text-neutral-600 border border-neutral-200
                         rounded-lg hover:bg-neutral-50 transition-colors min-h-[36px] flex items-center"
            >
              Lihat Semua ({data.total})
            </a>
          )}
        </div>
      </div>

      {/* Summary result */}
      {summary && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-xs font-medium text-blue-700 mb-1">Ringkasan Proyek</p>
          <p className="text-sm text-blue-800">{summary}</p>
        </div>
      )}

      {(!data || data.items.length === 0) ? (
        <p className="text-sm text-neutral-500 text-center py-4">
          Belum ada activity log untuk proyek ini.
        </p>
      ) : (
        <div className="space-y-2">
          {data.items.map((log) => (
            <div key={log.id_log} className="flex items-start gap-3 p-3 bg-neutral-50 rounded-lg">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full font-medium">
                    {log.subtask_category}
                  </span>
                  <span className="text-xs text-neutral-400">{log.duration_hours}h</span>
                  <span className="text-xs text-neutral-300">
                    {new Date(log.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "short" })}
                  </span>
                </div>
                <p className="text-sm text-neutral-700 line-clamp-2">{log.raw_notes}</p>
                {/* Action Items dari AI polishing */}
                {log.ai_polished_notes?.action_items && log.ai_polished_notes.action_items.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {log.ai_polished_notes.action_items.map((item, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800"
                        title={item.description}
                      >
                        <span className="text-amber-500">▸</span>
                        {item.description}
                        {item.pic && <span className="text-amber-600">(PIC: {item.pic})</span>}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
