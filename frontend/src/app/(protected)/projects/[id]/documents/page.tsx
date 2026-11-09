"use client";

import { useState, useCallback } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { DocumentForm } from "@/components/DocumentForm";
import { DQNumberInput } from "@/components/DQNumberInput";
import { RAGPanel } from "@/components/RAGPanel";
import {
  createDocument,
  getProjectDocuments,
  updateDocumentStatus,
  updateDQNumber,
  type Document,
  type DocStatus,
  type CreateDocumentInput,
} from "@/lib/api/documents";

/**
 * Halaman Document Tracking per Proyek
 *
 * Fitur:
 * - Tabel/list dokumen dengan kolom: tipe, status (badge), link GDrive, catatan
 * - Tombol tambah dokumen baru → modal form
 * - Tombol ubah status dokumen (transisi berurutan)
 * - Input DQ Number
 * - Loading skeleton saat fetch data
 * - Badge "Menunggu DQ" pada proyek tanpa DQ
 *
 * Requirements: 6.2, 7.1, 7.2
 */

// Warna badge berdasarkan status dokumen
function getDocStatusStyle(status: DocStatus): string {
  switch (status) {
    case "Draft":
      return "bg-neutral-100 text-neutral-700";
    case "Reviewed":
      return "bg-blue-100 text-blue-700";
    case "Final":
      return "bg-green-100 text-green-700";
    default:
      return "bg-neutral-100 text-neutral-700";
  }
}

// Status transisi berikutnya yang valid
function getNextStatus(current: DocStatus): DocStatus | null {
  switch (current) {
    case "Draft":
      return "Reviewed";
    case "Reviewed":
      return "Final";
    case "Final":
      return null; // Tidak bisa diubah lagi (kecuali Lead SA)
    default:
      return null;
  }
}

/** Interface data proyek untuk DQ Number */
interface ProjectDetail {
  id_project: string;
  project_name: string;
  customer_name: string;
  status: string;
  dq_number: string | null;
  use_case_tags?: string[];
}

export default function DocumentsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { user } = useAuthStore();

  // State UI
  const [showForm, setShowForm] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState<string | null>(null);
  const [isDQSubmitting, setIsDQSubmitting] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Fetch daftar dokumen
  const {
    data: documents,
    error: docError,
    isLoading: docLoading,
    mutate: mutateDocuments,
  } = useSWR<Document[]>(`/projects/${projectId}/documents`, () =>
    getProjectDocuments(projectId)
  );

  // Fetch detail proyek (untuk DQ Number)
  const {
    data: project,
    error: projError,
    mutate: mutateProject,
  } = useSWR<ProjectDetail>(`/projects/${projectId}`, fetcher);

  // Toast helper
  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
    const timeout = type === "success" ? 3000 : 5000;
    setTimeout(() => setToast(null), timeout);
  }, []);

  /**
   * Handle submit dokumen baru
   */
  const handleCreateDocument = useCallback(
    async (data: CreateDocumentInput) => {
      setIsCreating(true);
      try {
        await createDocument(projectId, data);
        await mutateDocuments();
        setShowForm(false);
        showToast("success", "Dokumen berhasil ditambahkan");
      } catch (err) {
        const message = err instanceof Error ? err.message : "Gagal menambahkan dokumen";
        showToast("error", message);
      } finally {
        setIsCreating(false);
      }
    },
    [projectId, mutateDocuments, showToast]
  );

  /**
   * Handle ubah status dokumen
   */
  const handleStatusChange = useCallback(
    async (docId: string, newStatus: DocStatus) => {
      setIsUpdatingStatus(docId);
      try {
        await updateDocumentStatus(docId, newStatus);
        await mutateDocuments();
        showToast("success", `Status berhasil diubah ke ${newStatus}`);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Gagal mengubah status";
        showToast("error", message);
      } finally {
        setIsUpdatingStatus(null);
      }
    },
    [mutateDocuments, showToast]
  );

  /**
   * Handle submit DQ Number
   */
  const handleDQSubmit = useCallback(
    async (dqNumber: string) => {
      setIsDQSubmitting(true);
      try {
        await updateDQNumber(projectId, dqNumber);
        await mutateProject();
        showToast("success", "DQ Number berhasil disimpan");
      } catch (err) {
        const message = err instanceof Error ? err.message : "Gagal menyimpan DQ Number";
        showToast("error", message);
      } finally {
        setIsDQSubmitting(false);
      }
    },
    [projectId, mutateProject, showToast]
  );

  // Cek apakah user bisa mengubah status dokumen Final
  const canChangeFinalStatus = user?.role === "Lead_SA" || user?.role === "Admin";

  // Cek apakah proyek sudah punya use_case_tags (sudah scoring)
  const projectHasTags = !!(project?.use_case_tags?.length);

  return (
    <div className="max-w-6xl mx-auto flex gap-6">
      {/* Konten utama */}
      <div className="flex-1 min-w-0 space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">
            Dokumen Proyek
          </h1>
          {project && (
            <p className="text-sm text-neutral-500 mt-1">
              {project.project_name} — {project.customer_name}
            </p>
          )}
        </div>

        {/* Badge Menunggu DQ */}
        {project && project.dq_number === null && (
          <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
            Menunggu DQ
          </span>
        )}
      </div>

      {/* DQ Number Section — dipindahkan ke halaman detail proyek */}

      {/* Daftar Dokumen */}
      <div className="bg-white border border-neutral-200 rounded-lg">
        {/* Header section */}
        <div className="flex items-center justify-between p-4 border-b border-neutral-100">
          <h2 className="text-base font-semibold text-neutral-800">
            Daftar Dokumen
          </h2>
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 rounded-lg font-medium text-white text-sm
                       bg-primary-600 hover:bg-primary-700 active:bg-primary-800
                       transition-colors duration-100 min-h-[44px]"
            aria-label="Tambah dokumen baru"
          >
            + Tambah Dokumen
          </button>
        </div>

        {/* Loading skeleton */}
        {docLoading && (
          <div className="p-4 space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse flex items-center gap-4">
                <div className="h-4 bg-neutral-200 rounded w-24" />
                <div className="h-4 bg-neutral-200 rounded w-16" />
                <div className="h-4 bg-neutral-200 rounded w-48 flex-1" />
                <div className="h-4 bg-neutral-200 rounded w-20" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {docError && (
          <div className="p-4">
            <p className="text-sm text-red-600" role="alert">
              Gagal memuat daftar dokumen. Silakan coba lagi.
            </p>
          </div>
        )}

        {/* Empty state */}
        {!docLoading && !docError && documents && documents.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-sm text-neutral-500">
              Belum ada dokumen. Klik &quot;Tambah Dokumen&quot; untuk memulai.
            </p>
          </div>
        )}

        {/* Tabel dokumen */}
        {!docLoading && documents && documents.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Daftar dokumen proyek">
              <thead>
                <tr className="border-b border-neutral-100">
                  <th className="text-left px-4 py-3 font-medium text-neutral-600">
                    Tipe
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-neutral-600">
                    Status
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-neutral-600">
                    Link GDrive
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-neutral-600">
                    Catatan
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-neutral-600">
                    Aksi
                  </th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const nextStatus = getNextStatus(doc.status);
                  const canChange =
                    doc.status === "Final" ? canChangeFinalStatus : true;

                  return (
                    <tr
                      key={doc.id_doc}
                      className="border-b border-neutral-50 hover:bg-neutral-50 transition-colors"
                    >
                      {/* Tipe dokumen */}
                      <td className="px-4 py-3 font-medium text-neutral-800">
                        {doc.doc_type}
                      </td>

                      {/* Status badge */}
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getDocStatusStyle(doc.status)}`}
                        >
                          {doc.status}
                        </span>
                      </td>

                      {/* Link GDrive — clickable */}
                      <td className="px-4 py-3">
                        <a
                          href={doc.gdrive_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary-600 hover:text-primary-700 hover:underline 
                                     inline-flex items-center gap-1 max-w-[200px]"
                          aria-label={`Buka dokumen ${doc.doc_type} di Google Drive`}
                        >
                          <span className="truncate">Buka di Drive</span>
                          <span aria-hidden="true">↗</span>
                        </a>
                      </td>

                      {/* Catatan */}
                      <td className="px-4 py-3 text-neutral-600 max-w-[200px] truncate">
                        {doc.notes || "—"}
                      </td>

                      {/* Aksi: ubah status */}
                      <td className="px-4 py-3">
                        {nextStatus && canChange ? (
                          <button
                            onClick={() => handleStatusChange(doc.id_doc, nextStatus)}
                            disabled={isUpdatingStatus === doc.id_doc}
                            className="px-3 py-1.5 rounded text-xs font-medium text-primary-700 
                                       bg-primary-50 hover:bg-primary-100 
                                       transition-colors duration-100 min-h-[44px] min-w-[44px]
                                       disabled:opacity-50 disabled:cursor-not-allowed"
                            aria-label={`Ubah status ${doc.doc_type} ke ${nextStatus}`}
                          >
                            {isUpdatingStatus === doc.id_doc ? (
                              <span className="flex items-center gap-1">
                                <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                </svg>
                                Mengubah...
                              </span>
                            ) : (
                              `→ ${nextStatus}`
                            )}
                          </button>
                        ) : doc.status === "Final" && !canChangeFinalStatus ? (
                          <span className="text-xs text-neutral-400">
                            Hanya Lead SA
                          </span>
                        ) : (
                          <span className="text-xs text-neutral-400">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Tutup flex-1 (konten utama) */}
      </div>

      {/* Sidebar — Panel Referensi Serupa (RAG) */}
      <div className="w-72 shrink-0 hidden lg:block">
        <div className="sticky top-6">
          <RAGPanel projectId={projectId} hasTags={projectHasTags} />
        </div>
      </div>

      {/* Modal Form Tambah Dokumen */}
      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          aria-label="Form tambah dokumen baru"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowForm(false);
          }}
        >
          <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-neutral-900">
                Tambah Dokumen Baru
              </h3>
              <button
                onClick={() => setShowForm(false)}
                className="p-2 rounded-lg hover:bg-neutral-100 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
                aria-label="Tutup form"
              >
                <svg className="w-5 h-5 text-neutral-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <DocumentForm
              onSubmit={handleCreateDocument}
              isSubmitting={isCreating}
              onCancel={() => setShowForm(false)}
            />
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <div
          className={`
            fixed bottom-6 right-6 z-50 max-w-sm px-4 py-3 rounded-lg shadow-lg
            ${toast.type === "success"
              ? "bg-green-50 border border-green-200 text-green-800"
              : "bg-red-50 border border-red-200 text-red-800"
            }
          `}
          role="status"
          aria-live="polite"
        >
          <div className="flex items-start gap-2">
            {toast.type === "success" ? (
              <svg className="w-5 h-5 text-green-500 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
            )}
            <p className="text-sm">{toast.message}</p>
          </div>
        </div>
      )}
    </div>
  );
}
