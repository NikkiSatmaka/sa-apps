"use client";

import { useState, useCallback } from "react";
import type { DocType, FolderType, CreateDocumentInput } from "@/lib/api/documents";

/**
 * Form untuk menambahkan dokumen baru ke proyek
 *
 * Fitur:
 * - Select tipe dokumen (PropTek, BOQ, Mandays, MoM, RFP, HLD)
 * - Input link GDrive (wajib)
 * - Select folder type (Inventory, Diagram, Solutions)
 * - Textarea catatan (max 500 karakter, dengan counter)
 * - Validasi client-side sebelum submit
 * - Loading state saat submit
 *
 * Requirements: 7.1, 7.2
 */

// Opsi tipe dokumen yang diunggah manual (Requirement dibuat otomatis oleh sistem)
const DOC_TYPE_OPTIONS: { value: DocType; label: string }[] = [
  { value: "PropTek", label: "PropTek" },
  { value: "BOQ", label: "BOQ" },
  { value: "Mandays", label: "Mandays" },
  { value: "MoM", label: "MoM" },
  { value: "RFP", label: "RFP" },
  { value: "HLD", label: "HLD" },
];

// Opsi folder type
const FOLDER_TYPE_OPTIONS: { value: FolderType; label: string }[] = [
  { value: "Inventory", label: "Inventory" },
  { value: "Diagram", label: "Diagram" },
  { value: "Solutions", label: "Solutions" },
];

// Batas maksimal karakter catatan
const MAX_NOTES_LENGTH = 500;

interface DocumentFormProps {
  /** Callback saat form disubmit dengan data valid */
  onSubmit: (data: CreateDocumentInput) => Promise<void>;
  /** Status loading saat submit */
  isSubmitting?: boolean;
  /** Callback untuk menutup form/modal */
  onCancel?: () => void;
}

interface FormErrors {
  doc_type?: string;
  gdrive_link?: string;
  folder_type?: string;
  notes?: string;
}

export function DocumentForm({ onSubmit, isSubmitting = false, onCancel }: DocumentFormProps) {
  // State form
  const [docType, setDocType] = useState<DocType | "">("");
  const [gdriveLink, setGdriveLink] = useState("");
  const [folderType, setFolderType] = useState<FolderType | "">("");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});

  /**
   * Validasi form sebelum submit
   */
  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!docType) {
      newErrors.doc_type = "Tipe dokumen wajib dipilih";
    }

    if (!gdriveLink.trim()) {
      newErrors.gdrive_link = "Link GDrive wajib diisi";
    } else if (!gdriveLink.trim().startsWith("http")) {
      newErrors.gdrive_link = "Link harus berupa URL yang valid";
    }

    if (!folderType) {
      newErrors.folder_type = "Folder tujuan wajib dipilih";
    }

    if (notes.length > MAX_NOTES_LENGTH) {
      newErrors.notes = `Catatan maksimal ${MAX_NOTES_LENGTH} karakter`;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [docType, gdriveLink, folderType, notes]);

  /**
   * Handle submit form
   */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!validate()) return;

      const data: CreateDocumentInput = {
        doc_type: docType as DocType,
        gdrive_link: gdriveLink.trim(),
        folder_type: folderType as FolderType,
        ...(notes.trim() && { notes: notes.trim() }),
      };

      await onSubmit(data);
    },
    [docType, gdriveLink, folderType, notes, validate, onSubmit]
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-5" aria-label="Form tambah dokumen">
      {/* Tipe Dokumen */}
      <div>
        <label
          htmlFor="doc-type"
          className="block text-sm font-medium text-neutral-700 mb-1"
        >
          Tipe Dokumen <span className="text-red-500">*</span>
        </label>
        <select
          id="doc-type"
          value={docType}
          onChange={(e) => {
            setDocType(e.target.value as DocType);
            if (errors.doc_type) setErrors((prev) => ({ ...prev, doc_type: undefined }));
          }}
          disabled={isSubmitting}
          className={`
            w-full px-3 py-2.5 border rounded-lg text-sm
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
            disabled:opacity-50 disabled:bg-neutral-100
            ${errors.doc_type ? "border-red-300 bg-red-50" : "border-neutral-300"}
          `}
          aria-invalid={!!errors.doc_type}
          aria-describedby={errors.doc_type ? "doc-type-error" : undefined}
        >
          <option value="">Pilih tipe dokumen...</option>
          {DOC_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {errors.doc_type && (
          <p id="doc-type-error" className="text-xs text-red-600 mt-1" role="alert">
            {errors.doc_type}
          </p>
        )}
      </div>

      {/* Link GDrive */}
      <div>
        <label
          htmlFor="gdrive-link"
          className="block text-sm font-medium text-neutral-700 mb-1"
        >
          Link Google Drive <span className="text-red-500">*</span>
        </label>
        <input
          id="gdrive-link"
          type="url"
          value={gdriveLink}
          onChange={(e) => {
            setGdriveLink(e.target.value);
            if (errors.gdrive_link) setErrors((prev) => ({ ...prev, gdrive_link: undefined }));
          }}
          disabled={isSubmitting}
          placeholder="https://drive.google.com/..."
          className={`
            w-full px-3 py-2.5 border rounded-lg text-sm
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
            disabled:opacity-50 disabled:bg-neutral-100
            ${errors.gdrive_link ? "border-red-300 bg-red-50" : "border-neutral-300"}
          `}
          aria-invalid={!!errors.gdrive_link}
          aria-describedby={errors.gdrive_link ? "gdrive-link-error" : undefined}
        />
        {errors.gdrive_link && (
          <p id="gdrive-link-error" className="text-xs text-red-600 mt-1" role="alert">
            {errors.gdrive_link}
          </p>
        )}
      </div>

      {/* Folder Type */}
      <div>
        <label
          htmlFor="folder-type"
          className="block text-sm font-medium text-neutral-700 mb-1"
        >
          Folder Tujuan <span className="text-red-500">*</span>
        </label>
        <select
          id="folder-type"
          value={folderType}
          onChange={(e) => {
            setFolderType(e.target.value as FolderType);
            if (errors.folder_type) setErrors((prev) => ({ ...prev, folder_type: undefined }));
          }}
          disabled={isSubmitting}
          className={`
            w-full px-3 py-2.5 border rounded-lg text-sm
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
            disabled:opacity-50 disabled:bg-neutral-100
            ${errors.folder_type ? "border-red-300 bg-red-50" : "border-neutral-300"}
          `}
          aria-invalid={!!errors.folder_type}
          aria-describedby={errors.folder_type ? "folder-type-error" : undefined}
        >
          <option value="">Pilih folder...</option>
          {FOLDER_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {errors.folder_type && (
          <p id="folder-type-error" className="text-xs text-red-600 mt-1" role="alert">
            {errors.folder_type}
          </p>
        )}
      </div>

      {/* Catatan */}
      <div>
        <label
          htmlFor="doc-notes"
          className="block text-sm font-medium text-neutral-700 mb-1"
        >
          Catatan <span className="text-neutral-400 font-normal">(opsional)</span>
        </label>
        <textarea
          id="doc-notes"
          value={notes}
          onChange={(e) => {
            setNotes(e.target.value);
            if (errors.notes) setErrors((prev) => ({ ...prev, notes: undefined }));
          }}
          disabled={isSubmitting}
          maxLength={MAX_NOTES_LENGTH}
          rows={3}
          placeholder="Catatan tambahan tentang dokumen ini..."
          className={`
            w-full px-3 py-2.5 border rounded-lg text-sm resize-none
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
            disabled:opacity-50 disabled:bg-neutral-100
            ${errors.notes ? "border-red-300 bg-red-50" : "border-neutral-300"}
          `}
          aria-invalid={!!errors.notes}
          aria-describedby="doc-notes-counter"
        />
        <div className="flex justify-between items-center mt-1">
          {errors.notes ? (
            <p className="text-xs text-red-600" role="alert">
              {errors.notes}
            </p>
          ) : (
            <span />
          )}
          <p
            id="doc-notes-counter"
            className={`text-xs ${
              notes.length > MAX_NOTES_LENGTH ? "text-red-600" : "text-neutral-400"
            }`}
          >
            {notes.length}/{MAX_NOTES_LENGTH}
          </p>
        </div>
      </div>

      {/* Tombol aksi */}
      <div className="flex gap-3 pt-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="flex-1 py-2.5 px-4 rounded-lg font-medium text-neutral-700
                       border border-neutral-300 hover:bg-neutral-50
                       transition-colors duration-100 min-h-[44px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Batal
          </button>
        )}
        <button
          type="submit"
          disabled={isSubmitting}
          className={`
            flex-1 py-2.5 px-4 rounded-lg font-medium text-white
            transition-all duration-200 min-h-[44px]
            ${isSubmitting
              ? "bg-neutral-400 cursor-not-allowed"
              : "bg-primary-600 hover:bg-primary-700 active:bg-primary-800"
            }
            disabled:opacity-50 disabled:cursor-not-allowed
          `}
        >
          {isSubmitting ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              Menyimpan...
            </span>
          ) : (
            "Simpan Dokumen"
          )}
        </button>
      </div>
    </form>
  );
}
