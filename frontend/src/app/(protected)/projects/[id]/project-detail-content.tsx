"use client";

import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { useState } from "react";
import useSWR from "swr";
import { apiRequest, fetcher } from "@/lib/fetcher";
import { isPrivileged } from "@/lib/roles";
import type { QualificationView } from "@/lib/qualification";
import type { IntegrationOperationResponse, CustomerOption } from "@/lib/api/projects";
import { repairProjectCustomerLink } from "@/lib/api/projects";
import type { HandoverReadiness } from "@/lib/api/handover";
import { BANTOverride } from "@/components/BANTOverride";
import { CollaboratorSection } from "@/components/CollaboratorSection";
import { HandoverAction } from "@/components/HandoverAction";
import { HandoverConfigForm } from "@/components/HandoverConfigForm";
import { HandoverModal } from "@/components/HandoverModal";
import { LoadError } from "@/components/LoadError";
import { PeopleSection } from "@/components/PeopleSection";
import { ProjectComments } from "@/components/ProjectComments";
import { QualificationSection } from "@/components/QualificationSection";
import { SourceDocumentSection, type SourceDocumentItem } from "@/components/SourceDocumentSection";
import { StatusActions } from "@/components/StatusActions";
import { StatusBadge } from "@/components/StatusBadge";
import { SubtaskSection } from "@/components/SubtaskSection";
import { ProjectIntegrationOperations } from "@/components/ProjectIntegrationOperations";
import { TimSASection } from "@/components/TimSASection";

type FolderProvisioningAttempt = {
  attempt: number;
  status: "pending" | "failed" | "succeeded";
  started_at: string;
  finished_at: string | null;
  outcome: string | null;
  actionable_error: string | null;
};
type FolderProvisioningOperation = {
  status: "pending" | "failed" | "succeeded";
  attempts: FolderProvisioningAttempt[];
  started_at: string | null;
  finished_at: string | null;
  outcome: string | null;
  actionable_error: string | null;
};
type Person = { id: string | null; name: string | null; email: string | null };

export interface ProjectDetail {
  id_project: string;
  customer_id?: string | null;
  project_name: string;
  customer_name: string;
  status: string;
  qualification_state?: string | null;
  previous_status?: string | null;
  lost_reason?: string | null;
  dq_number: string | null;
  bant_score: number | null;
  bant_detail: { budget_mrr?: number | null; pic_name?: string | null; pic_position?: string | null; pic_email?: string | null; need_description?: string | null; timeline_target?: string | null; [key: string]: unknown } | null;
  qualification?: QualificationView;
  use_case_tags: string[] | null;
  target_submit: string | null;
  created_by?: Person | null;
  product_pic?: Person | null;
  sales_pic: Person | null;
  lead_sa?: Person | null;
  assigned_sa: Person | null;
  collaborators: { id: string; user_id: string; user_name: string; user_email: string; user_role: string; role: "viewer" | "contributor"; added_by_name: string; created_at: string }[];
  source_documents?: SourceDocumentItem[];
  gdrive_folder_id: string | null;
  gdrive_solutions_folder_id?: string | null;
  gdrive_folder_number?: number | null;
  folder_provisioning_status: "pending" | "provisioned" | "failed" | null;
  folder_provisioning_operation?: FolderProvisioningOperation | null;
  integration_operations: IntegrationOperationResponse[];
  created_at: string;
  updated_at: string;
}

interface Props {
  project: ProjectDetail;
  projectId: string;
  user: { role: string; is_admin?: boolean | null } | null;
  bisa: (permission: "ubah_proyek" | "handover") => boolean;
  router: AppRouterInstance;
  onProjectChanged: () => void;
  onAssign: () => void;
  onReassign: () => void;
  onDelete: () => void;
  folderProvisioning: { isRetrying: boolean; error: string | null; onRetry: () => void };
  handover: { status?: HandoverReadiness; error?: unknown; onRetry: () => void; onSuccess: () => void; shouldShowConfigForm: boolean | undefined; shouldShowModal: boolean; onAcknowledge: () => void };
}

export function ProjectDetailContent({
  project,
  projectId,
  user,
  bisa,
  router,
  onProjectChanged,
  onAssign,
  onReassign,
  onDelete,
  folderProvisioning,
  handover,
}: Props) {
  const canDelete = isPrivileged(user);
  const canRepairCustomer = user?.role === "Lead_SA" || user?.is_admin === true;
  const [showCustomerRepair, setShowCustomerRepair] = useState(false);
  const [repairCustomerId, setRepairCustomerId] = useState("");
  const [repairReason, setRepairReason] = useState("");
  const [driveReviewed, setDriveReviewed] = useState(false);
  const [repairingCustomer, setRepairingCustomer] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const { data: customers = [], isLoading: customersLoading } = useSWR<CustomerOption[]>(
    showCustomerRepair && canRepairCustomer ? "/customers" : null,
    fetcher,
  );

  const handleRepairCustomer = async () => {
    setRepairingCustomer(true);
    setRepairError(null);
    try {
      await repairProjectCustomerLink(projectId, repairCustomerId, repairReason.trim());
      setShowCustomerRepair(false);
      setRepairCustomerId("");
      setRepairReason("");
      setDriveReviewed(false);
      onProjectChanged();
    } catch (cause) {
      setRepairError(cause instanceof Error ? cause.message : "Gagal memperbaiki tautan Customer.");
    } finally {
      setRepairingCustomer(false);
    }
  };

  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">{project.project_name}</h1>
          <p className="mt-1 text-sm text-neutral-500">{project.customer_name}</p>
          <p className="mt-0.5 font-mono text-xs text-neutral-400">{project.id_project}</p>
          <p className="mt-0.5 text-xs text-neutral-400">
            Terakhir Diubah:{" "}
            {new Date(project.updated_at).toLocaleDateString("id-ID", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {project.status === "Awaiting Assignment" && isPrivileged(user) && (
            <button
              onClick={onAssign}
              className="min-h-[36px] rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary-700"
            >
              Assign SA
            </button>
          )}
          <BANTOverride
            projectId={project.id_project}
            status={project.status}
            qualificationState={project.qualification_state}
            actor={user}
            currentScores={project.bant_detail}
          />
          {project.assigned_sa &&
            ["Awaiting Assignment", "Assigned", "In Progress", "Submitted"].includes(
              project.status,
            ) &&
            isPrivileged(user) && (
              <button
                onClick={onReassign}
                className="min-h-[36px] rounded-lg border border-amber-300 px-3 py-1.5 text-sm font-medium text-amber-700 transition-colors hover:bg-amber-50"
              >
                Reassign SA
              </button>
            )}
          {bisa("ubah_proyek") && (
            <button
              onClick={() => router.push(`/projects/${projectId}/edit`)}
              className="min-h-[36px] rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
            >
              Edit
            </button>
          )}
          {canDelete && (
            <button
              onClick={onDelete}
              className="min-h-[36px] rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50"
            >
              Hapus
            </button>
          )}
          <StatusBadge
            status={project.status}
            qualificationState={project.qualification_state}
            className="shrink-0 rounded-full px-3 py-1 text-xs"
          />
        </div>
      {canRepairCustomer && (
        <button
          type="button"
          onClick={() => setShowCustomerRepair(true)}
          className="min-h-[36px] rounded-lg border border-amber-300 px-3 py-1.5 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-50"
        >
          Perbaiki tautan Customer
        </button>
      )}
      </div>
      {showCustomerRepair && canRepairCustomer && (
        <div role="dialog" aria-modal="true" aria-labelledby="customer-repair-title" className="rounded-lg border border-amber-300 bg-amber-50 p-5">
          <h2 id="customer-repair-title" className="text-lg font-semibold text-neutral-900">Perbaiki tautan Customer proyek</h2>
          <p className="mt-2 text-sm text-neutral-700">
            Customer saat ini: <strong>{project.customer_name}</strong> ({project.customer_id || "belum ditautkan"})
          </p>
          <p className="mt-2 text-sm text-amber-900">
            Google Drive tidak akan dipindahkan atau diperbaiki oleh tindakan ini. Periksa folder dan permission yang ada di Google Drive sebelum menyimpan. Permission tidak diverifikasi otomatis.
          </p>
          <div className="mt-3 space-y-1 text-sm text-neutral-700">
            <p>Folder proyek: {project.gdrive_folder_id || "belum terdaftar"}</p>
            <p>Folder Solutions: {project.gdrive_solutions_folder_id || "belum terdaftar"}</p>
            <p>Nomor folder: {project.gdrive_folder_number ?? "belum ditetapkan"} · Status: {project.folder_provisioning_status || "belum ada"}</p>
            {project.gdrive_folder_id && (
              <a
                className="inline-block text-primary-700 underline"
                href={`https://drive.google.com/drive/folders/${project.gdrive_folder_id}`}
                target="_blank"
                rel="noreferrer"
              >
                Tinjau folder proyek di Google Drive
              </a>
            )}
            {project.gdrive_solutions_folder_id && (
              <a
                className="ml-3 inline-block text-primary-700 underline"
                href={`https://drive.google.com/drive/folders/${project.gdrive_solutions_folder_id}`}
                target="_blank"
                rel="noreferrer"
              >
                Tinjau folder Solutions di Google Drive
              </a>
            )}
          </div>
          <div className="mt-4 space-y-3">
            <label className="block text-sm font-medium text-neutral-800" htmlFor="customer-repair-select">Customer tujuan</label>
            <select
              id="customer-repair-select"
              value={repairCustomerId}
              onChange={(event) => setRepairCustomerId(event.target.value)}
              disabled={customersLoading}
              className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">Pilih Customer yang sudah ada</option>
              {customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}
            </select>
            {customers.length === 0 && !customersLoading && <p className="text-sm text-neutral-600">Belum ada Customer tersedia.</p>}
            <label className="block text-sm font-medium text-neutral-800" htmlFor="customer-repair-reason">Alasan perbaikan</label>
            <textarea
              id="customer-repair-reason"
              value={repairReason}
              onChange={(event) => setRepairReason(event.target.value)}
              required
              rows={3}
              className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-sm"
            />
            <label className="flex items-start gap-2 text-sm text-neutral-800">
              <input type="checkbox" checked={driveReviewed} onChange={(event) => setDriveReviewed(event.target.checked)} />
              <span>Saya sudah meninjau folder Drive dan permission yang ada.</span>
            </label>
            {repairError && <p role="alert" className="text-sm text-red-700">{repairError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleRepairCustomer}
                disabled={!repairCustomerId || !repairReason.trim() || !driveReviewed || repairingCustomer || customersLoading}
                className="rounded bg-primary-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {repairingCustomer ? "Menyimpan…" : "Simpan tautan Customer"}
              </button>
              <button type="button" onClick={() => setShowCustomerRepair(false)} className="rounded border border-neutral-300 px-3 py-2 text-sm">
                Batal
              </button>
            </div>
          </div>
        </div>
      )}
      <StatusActions project={project} onChanged={onProjectChanged} />
      <HandoverAction project={project} onDone={onProjectChanged} />
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-neutral-700">Informasi Proyek</h2>
        <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
          <InfoRow label="Dibuat oleh" value={project.created_by?.name || "—"} />
          <InfoRow label="Product Manager PIC" value={project.product_pic?.name || "—"} />
          <InfoRow label="Sales PIC" value={project.sales_pic?.name || "—"} />
          <InfoRow label="Lead SA" value={project.lead_sa?.name || "Belum ada"} />
          <InfoRow label="SA Ditugaskan" value={project.assigned_sa?.name || "Belum di-assign"} />
          <InfoRow label="DQ Number" value={project.dq_number || "Belum diinput"} mono={!!project.dq_number} />
          <InfoRow
            label="Target Submit"
            value={
              project.target_submit
                ? new Date(project.target_submit).toLocaleDateString("id-ID", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })
                : "—"
            }
          />
          <InfoRow
            label="Dibuat"
            value={new Date(project.created_at).toLocaleDateString("id-ID", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          />
        </div>
        {(project.use_case_tags?.length ?? 0) > 0 && (
          <div className="mt-4 border-t border-neutral-100 pt-4">
            <span className="text-xs text-neutral-500">Use Case Tags:</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {project.use_case_tags?.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-primary-50 px-2 py-0.5 text-xs text-primary-600"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </section>
      <FolderProvisioningSection
        status={project.folder_provisioning_status}
        operation={project.folder_provisioning_operation}
        masterFolderId={project.gdrive_folder_id}
        canRetry={isPrivileged(user)}
        isRetrying={folderProvisioning.isRetrying}
        retryError={folderProvisioning.error}
        onRetry={folderProvisioning.onRetry}
      />
      <ProjectIntegrationOperations
        projectId={projectId}
        operations={project.integration_operations ?? []}
        user={user}
        onRepaired={onProjectChanged}
      />
      <PeopleSection project={project} onChanged={onProjectChanged} />
      <div className="flex gap-4">
        <a
          href={`/projects/${projectId}/documents`}
          className="flex min-h-[44px] items-center gap-2 rounded-lg border border-neutral-200 px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
        >
          Dokumen
        </a>
        <a
          href={`/projects/${projectId}/activity-logs`}
          className="flex min-h-[44px] items-center gap-2 rounded-lg border border-neutral-200 px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
        >
          Riwayat Log
        </a>
      </div>
      {project.bant_score !== null && project.bant_score !== undefined && (
        <div
          className={`rounded-lg border p-4 ${
            project.bant_score >= 60
              ? "border-green-200 bg-green-50"
              : "border-amber-200 bg-amber-50"
          }`}
        >
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
      )}
      <QualificationSection qualification={project.qualification} targetSubmit={project.target_submit} />
      <SourceDocumentSection documents={project.source_documents ?? []} />
      <ProjectActivitySection projectId={projectId} />
      <TimSASection projectId={projectId} />
      <SubtaskSection projectId={projectId} />
      <ProjectComments projectId={projectId} readOnly={project.status === "Closed" || project.status === "Lost"} />
      <CollaboratorSection projectId={projectId} initialCollaborators={project.collaborators} />
      {project.status === "Won" && handover.error && !handover.status && (
        <LoadError message="Gagal memuat status handover." onRetry={handover.onRetry} />
      )}
      {handover.shouldShowConfigForm && (
        <div className="rounded-lg border border-amber-200 bg-white p-5">
          <h2 className="mb-3 text-base font-semibold text-neutral-800">Konfigurasi Handover</h2>
          <p className="mb-4 text-sm text-neutral-600">
            Email PMO Lead dan Delivery Lead belum dikonfigurasi.
          </p>
          <HandoverConfigForm
            projectId={projectId}
            existingPmoEmail={handover.status?.pmo_email}
            existingDeliveryEmail={handover.status?.delivery_email}
            onSuccess={handover.onSuccess}
          />
        </div>
      )}
      {handover.shouldShowModal && (
        <HandoverModal
          projectId={projectId}
          projectName={project.project_name}
          onAcknowledge={handover.onAcknowledge}
        />
      )}
    </>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  const missing = value.startsWith("Belum");

  return (
    <div>
      <span className="text-neutral-500">{label}:</span>
      <span
        className={`ml-2 font-medium ${
          missing
            ? "font-bold text-red-600"
            : mono
              ? "font-mono text-sm text-neutral-800"
              : "text-neutral-800"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function ProjectActivitySection({ projectId }: { projectId: string }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [isSummarizing, setIsSummarizing] = useState(false);
  const { data, isLoading, error, mutate } = useSWR<{
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

  const handleSummarize = async () => {
    if (!data || data.items.length === 0) return;

    setIsSummarizing(true);
    setSummary(null);
    try {
      const result = await apiRequest<{ summary: string }>(
        `/projects/${projectId}/summarize`,
        { method: "POST" },
      );
      setSummary(result.summary);
    } catch (err) {
      console.error("Summarize failed:", err);
      setSummary("Gagal menghasilkan ringkasan. Silakan coba lagi.");
    } finally {
      setIsSummarizing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="mb-4 h-5 w-1/4 animate-pulse rounded bg-neutral-200" />
        <div className="space-y-3 animate-pulse">
          <div className="h-10 rounded bg-neutral-100" />
          <div className="h-10 rounded bg-neutral-100" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-neutral-700">Project Story</h2>
          {data && data.total > 0 && (
            <p className="mt-0.5 text-xs text-neutral-400">
              {data.total} aktivitas — menampilkan 5 terbaru
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {data && data.total > 0 && (
            <button
              onClick={handleSummarize}
              disabled={isSummarizing}
              className="min-h-[36px] rounded-lg border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSummarizing ? "Generating..." : "Summarize"}
            </button>
          )}
          {data && data.total > 5 && (
            <a
              href={`/projects/${projectId}/activity-logs`}
              className="flex min-h-[36px] items-center rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 transition-colors hover:bg-neutral-50"
            >
              Lihat Semua ({data.total})
            </a>
          )}
        </div>
      </div>
      {summary && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="mb-1 text-xs font-medium text-blue-700">Ringkasan Proyek</p>
          <p className="text-sm text-blue-800">{summary}</p>
        </div>
      )}
      {error && !data ? (
        <LoadError
          message="Gagal memuat activity log proyek."
          onRetry={() => mutate()}
        />
      ) : !data || data.items.length === 0 ? (
        <p className="py-4 text-center text-sm text-neutral-500">
          Belum ada activity log untuk proyek ini.
        </p>
      ) : (
        <div className="space-y-2">
          {data.items.map((log) => (
            <div
              key={log.id_log}
              className="flex items-start gap-3 rounded-lg bg-neutral-50 p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="mb-0.5 flex items-center gap-2">
                  <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                    {log.subtask_category}
                  </span>
                  <span className="text-xs text-neutral-400">
                    {log.duration_hours}h
                  </span>
                  <span className="text-xs text-neutral-300">
                    {new Date(log.created_at).toLocaleDateString("id-ID", {
                      day: "numeric",
                      month: "short",
                    })}
                  </span>
                </div>
                <p className="line-clamp-2 text-sm text-neutral-700">{log.raw_notes}</p>
                {log.ai_polished_notes?.action_items &&
                  log.ai_polished_notes.action_items.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {log.ai_polished_notes.action_items.map((item, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800"
                          title={item.description}
                        >
                          ▸ {item.description}{" "}
                          {item.pic && (
                            <span className="text-amber-600">(PIC: {item.pic})</span>
                          )}
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

interface FolderProvisioningSectionProps {
  status: ProjectDetail["folder_provisioning_status"];
  operation?: FolderProvisioningOperation | null;
  masterFolderId: string | null;
  canRetry: boolean;
  isRetrying: boolean;
  retryError: string | null;
  onRetry: () => void;
}

function FolderProvisioningSection({
  status,
  operation,
  masterFolderId,
  canRetry,
  isRetrying,
  retryError,
  onRetry,
}: FolderProvisioningSectionProps) {
  const failed = status === "failed" || operation?.status === "failed";
  const pending =
    !failed && (status === "pending" || operation?.status === "pending");
  const provisioned =
    !failed && !pending && (status === "provisioned" || operation?.status === "succeeded");

  if (!failed && !pending && !provisioned) {
    return (
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-neutral-700">Folder Google Drive</h2>
        {masterFolderId ? (
          <a
            className="mt-2 inline-block text-sm font-medium text-primary-700 underline"
            href={`https://drive.google.com/drive/folders/${encodeURIComponent(masterFolderId)}`}
            target="_blank"
            rel="noreferrer"
          >
            Buka folder Google Drive
          </a>
        ) : (
          <p className="mt-2 text-sm text-neutral-600">Folder Google Drive belum terdaftar</p>
        )}
      </section>
    );
  }

  const latestAttempt = operation?.attempts.at(-1);
  const outcome = operation?.outcome ?? latestAttempt?.outcome;
  const actionableError =
    operation?.actionable_error ?? latestAttempt?.actionable_error;

  return (
    <section
      aria-labelledby="folder-provisioning-heading"
      aria-live="polite"
      className={`rounded-lg border p-5 ${
        failed
          ? "border-red-200 bg-red-50"
          : pending
            ? "border-amber-200 bg-amber-50"
            : "border-green-200 bg-green-50"
      }`}
    >
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-neutral-700">Folder Google Drive</h2>
        {masterFolderId ? (
          <a
            className="mt-2 inline-block text-sm font-medium text-primary-700 underline"
            href={`https://drive.google.com/drive/folders/${encodeURIComponent(masterFolderId)}`}
            target="_blank"
            rel="noreferrer"
          >
            Buka folder Google Drive
          </a>
        ) : (
          <p className="mt-2 text-sm text-neutral-600">Folder Google Drive belum terdaftar</p>
        )}
      </div>

      <h2
        id="folder-provisioning-heading"
        className="text-sm font-semibold text-neutral-800"
      >
        Provisioning folder Google Drive
      </h2>
      {failed ? (
        <p role="alert" className="mt-2 text-sm font-medium text-red-700">
          Provisioning folder gagal
        </p>
      ) : pending ? (
        <p role="status" className="mt-2 text-sm font-medium text-amber-800">
          Provisioning folder sedang diproses
        </p>
      ) : (
        <p role="status" className="mt-2 text-sm font-medium text-green-700">
          Folder Google Drive berhasil dibuat
        </p>
      )}
      {outcome && (
        <p className="mt-2 text-sm text-neutral-700">
          Hasil terakhir: <span>{outcome}</span>
        </p>
      )}
      {actionableError && (
        <p className="mt-2 text-sm text-neutral-700">{actionableError}</p>
      )}
      {operation?.attempts && operation.attempts.length > 0 && (
        <ol
          className="mt-3 space-y-1 text-xs text-neutral-600"
          aria-label="Riwayat percobaan provisioning"
        >
          {operation.attempts.map((attempt) => (
            <li key={`${attempt.attempt}-${attempt.started_at}`}>
              Percobaan {attempt.attempt}: {attempt.status}
              {attempt.finished_at &&
                ` — selesai ${new Date(attempt.finished_at).toLocaleString("id-ID")}`}
            </li>
          ))}
        </ol>
      )}
      {failed && canRetry && !masterFolderId && (
        <div className="mt-4">
          <p className="mb-3 text-sm text-neutral-700">
            Pastikan izin service account benar dan hapus folder yatim di Drive
            sebelum mencoba lagi.
          </p>
          <button
            type="button"
            onClick={onRetry}
            disabled={isRetrying}
            className="rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isRetrying ? "Memulai provisioning..." : "Coba provisioning lagi"}
          </button>
        </div>
      )}
      {failed && masterFolderId && (
        <p className="mt-3 text-sm text-neutral-700">
          Folder Drive sudah tersimpan; retry otomatis tidak tersedia. Periksa
          folder yang ada dan perbaiki izinnya secara manual.
        </p>
      )}
      {retryError && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {retryError}
        </p>
      )}
    </section>
  );

}

