"use client";

import { useCallback, useState, useRef } from "react";

/**
 * Komponen FileUpload — Reusable drag-and-drop file upload
 *
 * Fitur:
 * - Drag-and-drop zone dengan border dashed
 * - Validasi tipe file (PDF/DOCX)
 * - Validasi ukuran file (max 20MB)
 * - Daftar file dengan tombol hapus, ukuran, dan status validasi
 * - Maksimal 5 file per upload
 *
 * Requirements: 2.1, 2.3, 2.5, 2.6
 */

/** Tipe file yang diterima */
const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

/** Extension yang diterima untuk tampilan */
const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

/** Ukuran maksimal per file: 20MB */
const MAX_FILE_SIZE = 20 * 1024 * 1024;

/** Maksimal jumlah file */
const MAX_FILES = 5;

/** Tipe Source document (wajib dipilih per file) */
export type SourceDocType = "MoM" | "RFP";

/** Status validasi per file */
export interface FileItem {
  file: File;
  /** Tipe Source document; kosong = belum dipilih */
  docType?: SourceDocType | "";
  id: string;
  status: "valid" | "invalid_type" | "invalid_size";
  errorMessage?: string;
}

interface FileUploadProps {
  /** File yang sudah dipilih */
  files: FileItem[];
  /** Callback saat file berubah (ditambah/dihapus) */
  onChange: (files: FileItem[]) => void;
  /** Disabled state */
  disabled?: boolean;
}

/**
 * Validasi file berdasarkan tipe dan ukuran
 */
function validateFile(file: File): FileItem {
  const id = `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  // Cek tipe file
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return {
      file,
      id,
      status: "invalid_type",
      errorMessage: `Format tidak didukung. Hanya PDF dan DOCX yang diterima.`,
    };
  }

  // Cek ukuran file
  if (file.size > MAX_FILE_SIZE) {
    return {
      file,
      id,
      status: "invalid_size",
      errorMessage: `Ukuran file melebihi 20MB (${formatFileSize(file.size)}).`,
    };
  }

  return { file, id, status: "valid" };
}

/**
 * Format ukuran file ke string yang readable
 */
function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function FileUpload({ files, onChange, disabled = false }: FileUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Handler untuk file yang dipilih (dari input atau drag-drop)
  const handleFiles = useCallback(
    (newFiles: FileList | File[]) => {
      const fileArray = Array.from(newFiles);

      // Cek batas maksimal file
      const remainingSlots = MAX_FILES - files.length;
      if (remainingSlots <= 0) return;

      const filesToAdd = fileArray.slice(0, remainingSlots);
      const validated = filesToAdd.map(validateFile);
      onChange([...files, ...validated]);
    },
    [files, onChange]
  );

  // Drag events
  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (!disabled) setIsDragOver(true);
    },
    [disabled]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      if (disabled) return;
      if (e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files);
      }
    },
    [disabled, handleFiles]
  );

  // Handler klik zona upload
  const handleClick = useCallback(() => {
    if (!disabled && inputRef.current) {
      inputRef.current.click();
    }
  }, [disabled]);

  // Handler input file change
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files);
        // Reset input agar bisa pilih file yang sama
        e.target.value = "";
      }
    },
    [handleFiles]
  );

  // Ubah tipe Source document satu file
  const setDocType = useCallback(
    (id: string, docType: SourceDocType | "") => {
      onChange(files.map((f) => (f.id === id ? { ...f, docType } : f)));
    },
    [files, onChange]
  );

  // Hapus file dari daftar
  const removeFile = useCallback(
    (id: string) => {
      onChange(files.filter((f) => f.id !== id));
    },
    [files, onChange]
  );

  const validCount = files.filter((f) => f.status === "valid").length;

  return (
    <div className="space-y-3">
      {/* Drop Zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Area upload file. Klik atau drag file kesini."
        className={`
          relative border-2 border-dashed rounded-lg p-6 text-center cursor-pointer
          transition-all duration-200
          ${isDragOver ? "border-primary-500 bg-primary-50" : "border-neutral-300 hover:border-primary-400 hover:bg-neutral-50"}
          ${disabled ? "opacity-50 cursor-not-allowed" : ""}
          ${files.length >= MAX_FILES ? "opacity-50 cursor-not-allowed" : ""}
        `}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleClick();
        }}
      >
        {/* Icon upload */}
        <div className="flex flex-col items-center gap-2">
          <svg
            className={`w-10 h-10 ${isDragOver ? "text-primary-500" : "text-neutral-400"}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>

          <div>
            <p className="text-sm font-medium text-neutral-700">
              {isDragOver
                ? "Lepaskan file disini"
                : "Drag & drop file atau klik untuk memilih"}
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              PDF atau DOCX, maks 20MB per file, maks {MAX_FILES} file
            </p>
          </div>
        </div>

        {/* Hidden file input */}
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          multiple
          onChange={handleInputChange}
          disabled={disabled || files.length >= MAX_FILES}
          aria-hidden="true"
        />
      </div>

      {/* Info jumlah file */}
      {files.length > 0 && (
        <p className="text-xs text-neutral-500">
          {validCount} dari {MAX_FILES} file valid terpilih
        </p>
      )}

      {/* Daftar file yang dipilih */}
      {files.length > 0 && (
        <ul className="space-y-2" aria-label="Daftar file yang dipilih">
          {files.map((item) => (
            <li
              key={item.id}
              className={`
                flex items-center justify-between p-3 rounded-lg border text-sm
                ${item.status === "valid"
                  ? "bg-white border-neutral-200"
                  : "bg-red-50 border-red-200"
                }
              `}
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                {/* Icon tipe file */}
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded flex items-center justify-center text-xs font-semibold ${
                    item.file.type === "application/pdf"
                      ? "bg-red-100 text-red-700"
                      : "bg-blue-100 text-blue-700"
                  }`}
                >
                  {item.file.type === "application/pdf" ? "PDF" : "DOC"}
                </div>

                <div className="min-w-0 flex-1">
                  {/* Nama file */}
                  <p className="font-medium text-neutral-800 truncate">
                    {item.file.name}
                  </p>
                  {/* Ukuran file + status */}
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-neutral-500">
                      {formatFileSize(item.file.size)}
                    </span>
                    {item.status === "valid" && (
                      <span className="text-xs text-green-600 font-medium">
                        ✓ Valid
                      </span>
                    )}
                    {item.status !== "valid" && (
                      <span className="text-xs text-red-600 font-medium">
                        ✗ {item.errorMessage}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Tipe Source document (wajib) */}
              {item.status === "valid" && (
                <select
                  value={item.docType ?? ""}
                  onChange={(e) => setDocType(item.id, e.target.value as SourceDocType | "")}
                  disabled={disabled}
                  required
                  aria-label={`Tipe dokumen ${item.file.name}`}
                  className="flex-shrink-0 ml-2 text-xs border border-neutral-300 rounded-md px-2 py-1.5 bg-white"
                >
                  <option value="">Pilih tipe…</option>
                  <option value="MoM">MoM</option>
                  <option value="RFP">RFP</option>
                </select>
              )}

              {/* Tombol hapus */}
              <button
                type="button"
                onClick={() => removeFile(item.id)}
                disabled={disabled}
                className="flex-shrink-0 ml-2 p-1.5 rounded-md hover:bg-neutral-100 text-neutral-400 hover:text-red-500 transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center"
                aria-label={`Hapus file ${item.file.name}`}
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
