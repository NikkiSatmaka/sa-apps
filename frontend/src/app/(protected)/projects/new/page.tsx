"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { FileUpload, FileItem } from "@/components/FileUpload";
import { QualificationForm } from "@/components/QualificationForm";
import {
  createProject,
  extractFieldErrors,
  CreateProjectResponse,
} from "@/lib/api/projects";
import {
  QualificationAnswers,
  QualificationErrors,
  toPayload,
  useQualificationSchema,
  validateAnswers,
} from "@/lib/qualification";

/** User kandidat Product/Sales PIC (GET /projects/users/search?role=...). */
interface OrangOption {
  id: string;
  name: string;
  email: string;
}

/**
 * Halaman Form Request SA
 *
 * Fitur:
 * - Input fields: nama proyek, nama customer, target submit, estimasi nilai
 * - File upload drag-and-drop (PDF/DOCX, max 20MB, max 5 file)
 * - Client-side validation
 * - Dua langkah: (1) data dasar + file, (2) Kuesioner kualifikasi; satu kali pengiriman
 * - Skor BANT dihitung backend dari jawaban kuesioner (tidak ada form BANT manual)
 * - Feedback BANT score dan status perubahan
 *
 * Requirements: 2.1, 2.3, 2.7, 3.6
 */

// ==================== Types ====================

interface FormData {
  projectName: string;
  customerName: string;
  targetSubmit: string;
  estimatedValue: string;
  dqNumber: string;
  productPic: string;
  salesPic: string;
}

interface FormErrors {
  projectName?: string;
  customerName?: string;
  targetSubmit?: string;
  estimatedValue?: string;
  dqNumber?: string;
  productPic?: string;
  files?: string;
}

// ==================== Helpers ====================

/**
 * Format angka ke format IDR (titik sebagai pemisah ribuan)
 */
function formatIDR(value: string): string {
  // Hapus semua karakter non-digit dan non-dot/comma
  const cleaned = value.replace(/[^\d]/g, "");
  if (!cleaned) return "";

  // Format dengan pemisah ribuan
  return cleaned.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/**
 * Parse string IDR ke angka
 */
function parseIDR(value: string): number {
  const cleaned = value.replace(/\./g, "");
  return parseInt(cleaned) || 0;
}

/**
 * Dapatkan tanggal hari ini dalam format YYYY-MM-DD (untuk min date picker)
 */
function getTodayString(): string {
  const today = new Date();
  return today.toISOString().split("T")[0];
}

// ==================== Component ====================

export default function NewProjectPage() {
  const router = useRouter();
  const currentUser = useAuthStore((state) => state.user);

  // ADR 0014: pembuat Product otomatis jadi Product PIC; pembuat Sales otomatis jadi Sales PIC.
  const perluPilihProduct = currentUser?.role !== "Product";
  const bolehPilihSales = currentUser?.role !== "Sales";
  const { data: daftarProduct } = useSWR<OrangOption[]>(
    perluPilihProduct ? "/projects/users/search?role=Product&limit=50" : null,
    fetcher
  );
  const { data: daftarSales } = useSWR<OrangOption[]>(
    bolehPilihSales ? "/projects/users/search?role=Sales&limit=50" : null,
    fetcher
  );

  // Form state
  const [form, setForm] = useState<FormData>({
    projectName: "",
    customerName: "",
    targetSubmit: "",
    estimatedValue: "",
    dqNumber: "",
    productPic: "",
    salesPic: "",
  });
  const [files, setFiles] = useState<FileItem[]>([]);
  const [errors, setErrors] = useState<FormErrors>({});

  // Wizard: langkah 1 = data dasar + file, langkah 2 = kuesioner kualifikasi.
  // State dimiliki komponen ini sehingga kembali ke langkah 1 tidak menghilangkan isian.
  const [step, setStep] = useState<1 | 2>(1);
  const [answers, setAnswers] = useState<QualificationAnswers>({});
  const [answerErrors, setAnswerErrors] = useState<QualificationErrors>({});
  const { schema, error: schemaError } = useQualificationSchema();

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Post-submit state
  const [createdProject, setCreatedProject] = useState<CreateProjectResponse | null>(null);

  // Toast notification
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Tampilkan toast dengan auto-dismiss
  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
    const timeout = type === "success" ? 3000 : 5000;
    setTimeout(() => setToast(null), timeout);
  }, []);

  // File valid saja (untuk dikirim ke backend)
  const validFiles = useMemo(
    () => files.filter((f) => f.status === "valid"),
    [files]
  );

  // ==================== Validation ====================

  /**
   * Validasi form sebelum submit
   * Returns true jika valid, false jika ada error
   */
  const validateForm = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    // Nama proyek: wajib, max 150 karakter
    if (!form.projectName.trim()) {
      newErrors.projectName = "Nama proyek wajib diisi";
    } else if (form.projectName.trim().length > 150) {
      newErrors.projectName = "Nama proyek maksimal 150 karakter";
    }

    // Nama customer: wajib, max 150 karakter
    if (!form.customerName.trim()) {
      newErrors.customerName = "Nama customer wajib diisi";
    } else if (form.customerName.trim().length > 150) {
      newErrors.customerName = "Nama customer maksimal 150 karakter";
    }

    // Target submit: wajib, tidak boleh di masa lalu
    if (!form.targetSubmit) {
      newErrors.targetSubmit = "Target submit wajib diisi";
    } else {
      const selectedDate = new Date(form.targetSubmit);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      if (selectedDate < today) {
        newErrors.targetSubmit = "Target submit tidak boleh tanggal di masa lalu";
      }
    }

    // Estimasi nilai: wajib, rentang 0.01 - 999,999,999,999
    const numericValue = parseIDR(form.estimatedValue);
    if (!form.estimatedValue.trim()) {
      newErrors.estimatedValue = "Estimasi nilai proyek wajib diisi";
    } else if (numericValue < 1) {
      newErrors.estimatedValue = "Estimasi nilai minimal Rp 1";
    } else if (numericValue > 999999999999) {
      newErrors.estimatedValue = "Estimasi nilai maksimal Rp 999.999.999.999";
    }

    // DQ Number: opsional, tapi kalau diisi harus valid (alfanumerik + hyphen, 5-20 karakter)
    if (form.dqNumber.trim()) {
      const dqRegex = /^[A-Za-z0-9\-]{5,20}$/;
      if (!dqRegex.test(form.dqNumber.trim())) {
        newErrors.dqNumber = "Format DQ Number tidak valid (alfanumerik + hyphen, 5-20 karakter)";
      }
    }

    // Product PIC: wajib bila pembuat bukan Product (ADR 0014)
    if (perluPilihProduct && !form.productPic) {
      newErrors.productPic = "Product PIC wajib dipilih";
    }

    // Tipe Source document (MoM/RFP) wajib dipilih untuk setiap file valid
    if (validFiles.some((f) => !f.docType)) {
      newErrors.files = "Pilih tipe (MoM atau RFP) untuk setiap file";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [form, validFiles, perluPilihProduct]);

  // ==================== Handlers ====================

  // Update form field
  const updateField = useCallback(
    (field: keyof FormData, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }));
      // Clear error saat user mulai mengetik
      if (errors[field as keyof FormErrors]) {
        setErrors((prev) => ({ ...prev, [field]: undefined }));
      }
    },
    [errors]
  );

  // Update jawaban kuesioner
  const updateAnswer = useCallback(
    (field: string, value: string) => {
      setAnswers((prev) => ({ ...prev, [field]: value }));
      setAnswerErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
    },
    []
  );

  // Pemetaan field backend → field form langkah 1
  const HEADER_FIELDS: Record<string, keyof FormErrors> = {
    project_name: "projectName",
    customer_name: "customerName",
    target_submit: "targetSubmit",
    estimasi_nilai: "estimatedValue",
    dq_number: "dqNumber",
    product_pic: "productPic",
  };

  // Kirim seluruh data (langkah 1 + 2) dalam satu permintaan
  const submitAll = useCallback(async () => {
    setSubmitError(null);

    if (!schema) {
      setSubmitError("Skema kuesioner belum dimuat. Muat ulang halaman.");
      return;
    }
    const answerValidation = validateAnswers(schema, answers);
    setAnswerErrors(answerValidation);
    if (Object.keys(answerValidation).length > 0) return;

    setIsSubmitting(true);

    try {
      // Buat FormData untuk multipart/form-data
      const formData = new window.FormData();
      formData.append("project_name", form.projectName.trim());
      formData.append("customer_name", form.customerName.trim());
      formData.append("target_submit", form.targetSubmit);
      formData.append("estimasi_nilai", parseIDR(form.estimatedValue).toString());

      // Orang per project: Product wajib (kecuali pembuat Product), Sales opsional
      if (perluPilihProduct && form.productPic) formData.append("product_pic", form.productPic);
      if (bolehPilihSales && form.salesPic) formData.append("sales_pic", form.salesPic);

      // DQ Number opsional
      if (form.dqNumber.trim()) {
        formData.append("dq_number", form.dqNumber.trim());
      }

      formData.append("qualification_answers", JSON.stringify(toPayload(schema, answers)));

      // Tambahkan file valid
      validFiles.forEach((item) => {
        formData.append("files", item.file);
        formData.append("file_types", item.docType ?? "");
      });

      const response = await createProject(formData);
      setCreatedProject(response);

      if (response.scoring_triggered) {
        showToast("success", "Proyek berhasil dibuat! File sedang diproses untuk scoring.");
        // Redirect ke detail proyek setelah 2 detik: lihat useEffect di bawah (dibersihkan saat unmount)
      } else if (response.status === "Pending Assignment") {
        showToast("success", `BANT Score: ${response.bant_score} — Proyek masuk antrian assignment!`);
      } else {
        showToast("error", `BANT Score: ${response.bant_score} — Perlu klarifikasi tambahan.`);
      }
    } catch (err) {
      // Petakan error 422 per field ke form
      const fieldErrors = extractFieldErrors(err);
      const headerErrs: FormErrors = {};
      const answerErrs: QualificationErrors = {};
      for (const { field, reason } of fieldErrors) {
        if (field.startsWith("qualification_answers.")) {
          answerErrs[field.split(".")[1]] = reason;
        } else if (HEADER_FIELDS[field]) {
          headerErrs[HEADER_FIELDS[field]] = reason;
        }
      }
      if (Object.keys(headerErrs).length > 0) {
        setErrors(headerErrs);
        setStep(1);
      }
      if (Object.keys(answerErrs).length > 0) setAnswerErrors(answerErrs);

      const message =
        err instanceof Error ? err.message : "Terjadi kesalahan saat submit";
      setSubmitError(message);
      showToast("error", message);
    } finally {
      setIsSubmitting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, answers, schema, validFiles, router, showToast, perluPilihProduct, bolehPilihSales]);

  // Scoring berjalan (ada file): arahkan ke detail proyek setelah 2 detik. Timer dibersihkan saat
  // unmount agar berpindah halaman lebih dulu tidak memicu navigasi paksa.
  const redirectProjectId = createdProject?.scoring_triggered ? createdProject.id_project : null;
  useEffect(() => {
    if (!redirectProjectId) return;
    const timer = setTimeout(() => router.push(`/projects/${redirectProjectId}`), 2000);
    return () => clearTimeout(timer);
  }, [redirectProjectId, router]);

  // Submit form: langkah 1 → lanjut ke langkah 2; langkah 2 → kirim
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitError(null);

      if (step === 1) {
        if (validateForm()) setStep(2);
        return;
      }
      await submitAll();
    },
    [step, validateForm, submitAll]
  );

  // ==================== Render ====================

  // Jika sudah submit dan skor langsung tersedia (tanpa file) → tampilkan feedback
  if (createdProject && createdProject.bant_score !== null && createdProject.sub_scores) {
    return (
      <div className="max-w-2xl mx-auto">
        <BANTResultFeedback
          result={createdProject}
          projectName={createdProject.project_name}
          onViewProject={() => router.push(`/projects/${createdProject.id_project}`)}
        />
        {toast && <Toast type={toast.type} message={toast.message} />}
      </div>
    );
  }

  // Proyek sudah dibuat tetapi tanpa rincian skor (scoring berjalan, atau skor tanpa sub-skor):
  // ganti form dengan layar hasil agar form tidak bisa dikirim ulang (proyek duplikat).
  if (createdProject) {
    return (
      <div className="max-w-2xl mx-auto">
        <ProjectCreatedNotice
          result={createdProject}
          onViewProject={() => router.push(`/projects/${createdProject.id_project}`)}
        />
        {toast && <Toast type={toast.type} message={toast.message} />}
      </div>
    );
  }

  // Form utama
  return (
    <div className="max-w-2xl mx-auto">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-neutral-900">
          Request SA
        </h1>
        <p className="text-sm text-neutral-500 mt-1">
          Langkah {step} dari 2 —{" "}
          {step === 1 ? "Data dasar dan file" : "Kuesioner kualifikasi"}
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6" noValidate>
        {step === 1 && (
        <>
        <div className="bg-white rounded-lg border border-neutral-200 p-6 space-y-5">
          {/* Nama Proyek */}
          <div>
            <label
              htmlFor="projectName"
              className="block text-sm font-medium text-neutral-700 mb-1"
            >
              Nama Proyek <span className="text-red-500">*</span>
            </label>
            <input
              id="projectName"
              type="text"
              maxLength={150}
              value={form.projectName}
              onChange={(e) => updateField("projectName", e.target.value)}
              disabled={isSubmitting}
              placeholder="Contoh: Migrasi Data Warehouse ke Cloud"
              className={`
                w-full px-3 py-2.5 border rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                disabled:opacity-50 disabled:bg-neutral-100
                ${errors.projectName ? "border-red-300 bg-red-50" : "border-neutral-300"}
              `}
              aria-invalid={!!errors.projectName}
              aria-describedby={errors.projectName ? "projectName-error" : undefined}
            />
            {errors.projectName && (
              <p id="projectName-error" className="text-xs text-red-600 mt-1" role="alert">
                {errors.projectName}
              </p>
            )}
            <p className="text-xs text-neutral-400 mt-1">
              {form.projectName.length}/150 karakter
            </p>
          </div>

          {/* Nama Customer */}
          <div>
            <label
              htmlFor="customerName"
              className="block text-sm font-medium text-neutral-700 mb-1"
            >
              Nama Customer <span className="text-red-500">*</span>
            </label>
            <input
              id="customerName"
              type="text"
              maxLength={150}
              value={form.customerName}
              onChange={(e) => updateField("customerName", e.target.value)}
              disabled={isSubmitting}
              placeholder="Contoh: PT Astra International"
              className={`
                w-full px-3 py-2.5 border rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                disabled:opacity-50 disabled:bg-neutral-100
                ${errors.customerName ? "border-red-300 bg-red-50" : "border-neutral-300"}
              `}
              aria-invalid={!!errors.customerName}
              aria-describedby={errors.customerName ? "customerName-error" : undefined}
            />
            {errors.customerName && (
              <p id="customerName-error" className="text-xs text-red-600 mt-1" role="alert">
                {errors.customerName}
              </p>
            )}
            <p className="text-xs text-neutral-400 mt-1">
              {form.customerName.length}/150 karakter
            </p>
          </div>

          {/* Target Submit Date */}
          <div>
            <label
              htmlFor="targetSubmit"
              className="block text-sm font-medium text-neutral-700 mb-1"
            >
              Target Submit <span className="text-red-500">*</span>
            </label>
            <input
              id="targetSubmit"
              type="date"
              min={getTodayString()}
              value={form.targetSubmit}
              onChange={(e) => updateField("targetSubmit", e.target.value)}
              disabled={isSubmitting}
              className={`
                w-full px-3 py-2.5 border rounded-lg text-sm
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                disabled:opacity-50 disabled:bg-neutral-100
                ${errors.targetSubmit ? "border-red-300 bg-red-50" : "border-neutral-300"}
              `}
              aria-invalid={!!errors.targetSubmit}
              aria-describedby={errors.targetSubmit ? "targetSubmit-error" : undefined}
            />
            {errors.targetSubmit && (
              <p id="targetSubmit-error" className="text-xs text-red-600 mt-1" role="alert">
                {errors.targetSubmit}
              </p>
            )}
          </div>

          {/* Estimasi Nilai Proyek */}
          <div>
            <label
              htmlFor="estimatedValue"
              className="block text-sm font-medium text-neutral-700 mb-1"
            >
              Estimasi Nilai Proyek (IDR) <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-neutral-500">
                Rp
              </span>
              <input
                id="estimatedValue"
                type="text"
                inputMode="numeric"
                value={form.estimatedValue}
                onChange={(e) => updateField("estimatedValue", formatIDR(e.target.value))}
                disabled={isSubmitting}
                placeholder="0"
                className={`
                  w-full pl-9 pr-3 py-2.5 border rounded-lg text-sm
                  focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                  disabled:opacity-50 disabled:bg-neutral-100
                  ${errors.estimatedValue ? "border-red-300 bg-red-50" : "border-neutral-300"}
                `}
                aria-invalid={!!errors.estimatedValue}
                aria-describedby={errors.estimatedValue ? "estimatedValue-error" : undefined}
              />
            </div>
            {errors.estimatedValue && (
              <p id="estimatedValue-error" className="text-xs text-red-600 mt-1" role="alert">
                {errors.estimatedValue}
              </p>
            )}
          </div>

          {/* Product PIC (wajib bila pembuat bukan Product) */}
          {perluPilihProduct && (
            <div>
              <label htmlFor="productPic" className="block text-sm font-medium text-neutral-700 mb-1">
                Product PIC <span className="text-red-500">*</span>
              </label>
              <select
                id="productPic"
                value={form.productPic}
                onChange={(e) => updateField("productPic", e.target.value)}
                disabled={isSubmitting}
                required
                className={`
                  w-full px-3 py-2.5 border rounded-lg text-sm bg-white
                  focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                  disabled:opacity-50 disabled:bg-neutral-100
                  ${errors.productPic ? "border-red-300 bg-red-50" : "border-neutral-300"}
                `}
                aria-invalid={!!errors.productPic}
                aria-describedby={errors.productPic ? "productPic-error" : undefined}
              >
                <option value="">Pilih Product…</option>
                {(daftarProduct ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.email})
                  </option>
                ))}
              </select>
              {errors.productPic && (
                <p id="productPic-error" className="text-xs text-red-600 mt-1" role="alert">
                  {errors.productPic}
                </p>
              )}
            </div>
          )}

          {/* Sales PIC (opsional; pembuat Sales otomatis dirinya sendiri) */}
          {bolehPilihSales && (
            <div>
              <label htmlFor="salesPic" className="block text-sm font-medium text-neutral-700 mb-1">
                Sales PIC <span className="text-neutral-400 text-xs font-normal">(opsional)</span>
              </label>
              <select
                id="salesPic"
                value={form.salesPic}
                onChange={(e) => updateField("salesPic", e.target.value)}
                disabled={isSubmitting}
                className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:opacity-50 disabled:bg-neutral-100"
              >
                <option value="">Tanpa Sales</option>
                {(daftarSales ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.email})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* DQ Number (Opsional) */}
          <div>
            <label
              htmlFor="dqNumber"
              className="block text-sm font-medium text-neutral-700 mb-1"
            >
              DQ Number <span className="text-neutral-400 text-xs font-normal">(opsional)</span>
            </label>
            <input
              id="dqNumber"
              type="text"
              maxLength={20}
              value={form.dqNumber}
              onChange={(e) => updateField("dqNumber", e.target.value)}
              disabled={isSubmitting}
              placeholder="Contoh: DQ-2025-00123"
              className={`
                w-full px-3 py-2.5 border rounded-lg text-sm font-mono
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                disabled:opacity-50 disabled:bg-neutral-100
                ${errors.dqNumber ? "border-red-300 bg-red-50" : "border-neutral-300"}
              `}
              aria-invalid={!!errors.dqNumber}
              aria-describedby={errors.dqNumber ? "dqNumber-error" : undefined}
            />
            {errors.dqNumber && (
              <p id="dqNumber-error" className="text-xs text-red-600 mt-1" role="alert">
                {errors.dqNumber}
              </p>
            )}
            <p className="text-xs text-neutral-400 mt-1">
              Alfanumerik + tanda hubung, 5-20 karakter. Bisa diisi nanti.
            </p>
          </div>
        </div>

        {/* File Upload Section */}
        <div className="bg-white rounded-lg border border-neutral-200 p-6">
          <div className="mb-4">
            <h2 className="text-sm font-medium text-neutral-700">
              Source document
            </h2>
            <p className="text-xs text-neutral-500 mt-0.5">
              Upload dokumen referensi (opsional). Penilaian kelayakan berdasarkan
              Kuesioner kualifikasi di langkah berikutnya.
            </p>
          </div>

          <FileUpload
            files={files}
            onChange={(next) => {
              setFiles(next);
              if (errors.files) setErrors((prev) => ({ ...prev, files: undefined }));
            }}
            disabled={isSubmitting}
          />
          {errors.files && (
            <p className="text-xs text-red-600 mt-1" role="alert">
              {errors.files}
            </p>
          )}
        </div>
        </>
        )}

        {step === 2 && !schema && (
          <p className="text-sm text-neutral-500" role="status">
            {schemaError ? "Gagal memuat kuesioner. Muat ulang halaman." : "Memuat kuesioner..."}
          </p>
        )}
        {step === 2 && schema && (
          <QualificationForm
            schema={schema}
            answers={answers}
            errors={answerErrors}
            onChange={updateAnswer}
            disabled={isSubmitting}
          />
        )}

        {/* Error message global */}
        {submitError && (
          <div
            className="bg-red-50 border border-red-200 rounded-lg p-4"
            role="alert"
          >
            <p className="text-sm text-red-800 font-medium">Gagal submit:</p>
            <p className="text-sm text-red-700 mt-0.5">{submitError}</p>
          </div>
        )}

        {/* Tombol aksi */}
        <div className="flex gap-3">
          {step === 2 && (
            <button
              type="button"
              onClick={() => setStep(1)}
              disabled={isSubmitting}
              className="py-3 px-4 rounded-lg font-medium text-neutral-700 border border-neutral-300 bg-white hover:bg-neutral-50 disabled:opacity-50 min-h-touch"
            >
              Kembali
            </button>
          )}
          <button
            type="submit"
            disabled={isSubmitting}
            className={`
              flex-1 py-3 px-4 rounded-lg font-medium text-white transition-all duration-200
              ${isSubmitting
                ? "bg-neutral-400 cursor-not-allowed"
                : "bg-primary-600 hover:bg-primary-700 active:bg-primary-800"
              }
              disabled:opacity-50 disabled:cursor-not-allowed
              min-h-touch
            `}
          >
            {isSubmitting
              ? "Mengirim request..."
              : step === 1
                ? "Lanjut ke Kuesioner"
                : `Submit Request${validFiles.length > 0 ? ` (${validFiles.length} file)` : ""}`}
          </button>
        </div>
      </form>

      {/* Toast Notification */}
      {toast && <Toast type={toast.type} message={toast.message} />}
    </div>
  );
}

// ==================== Sub-Components ====================

/**
 * Komponen Toast Notification
 * Auto-dismiss: sukses 3s, error 5s (Requirement 19.4)
 */
function Toast({ type, message }: { type: "success" | "error"; message: string }) {
  return (
    <div
      className={`
        fixed bottom-6 right-6 z-50 max-w-sm px-4 py-3 rounded-lg shadow-lg
        animate-[slideIn_200ms_ease-out]
        ${type === "success" ? "toast-success" : "toast-error"}
      `}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-2">
        {type === "success" ? (
          <svg className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
        ) : (
          <svg className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clipRule="evenodd"
            />
          </svg>
        )}
        <p className="text-sm">{message}</p>
      </div>
    </div>
  );
}

/**
 * Layar konfirmasi setelah proyek dibuat tanpa rincian skor (#83).
 * Menggantikan form sehingga tidak ada tombol submit yang bisa ditekan lagi.
 */
function ProjectCreatedNotice({
  result,
  onViewProject,
}: {
  result: CreateProjectResponse;
  onViewProject: () => void;
}) {
  const detail = result.scoring_triggered
    ? "File sedang dianalisis AI untuk scoring. Anda akan diarahkan ke detail proyek."
    : result.status === "Pending Assignment"
      ? `BANT Score ${result.bant_score} — proyek masuk antrian assignment.`
      : `BANT Score ${result.bant_score} — perlu klarifikasi tambahan.`;

  return (
    <div className="space-y-4 rounded-lg border border-neutral-200 bg-white p-8 text-center">
      <h2 className="text-xl font-bold text-neutral-900">Request SA terkirim</h2>
      <p className="text-sm text-neutral-600">{result.project_name}</p>
      <p className="text-sm text-neutral-600">{detail}</p>
      <button
        type="button"
        onClick={onViewProject}
        className="py-3 px-6 rounded-lg font-medium text-white bg-primary-600 hover:bg-primary-700 min-h-touch"
      >
        Lihat Proyek
      </button>
    </div>
  );
}

/**
 * Komponen feedback hasil BANT scoring
 * Tampil setelah proyek dibuat tanpa file (skor langsung dihitung backend)
 */
function BANTResultFeedback({
  result,
  projectName,
  onViewProject,
}: {
  result: CreateProjectResponse;
  projectName: string;
  onViewProject: () => void;
}) {
  const isPass = (result.bant_score ?? 0) >= 60;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center">
        <div
          className={`inline-flex items-center justify-center w-16 h-16 rounded-full mb-4 ${
            isPass ? "bg-green-100" : "bg-red-100"
          }`}
        >
          {isPass ? (
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          )}
        </div>
        <h2 className="text-xl font-bold text-neutral-900">{projectName}</h2>
        <p className="text-sm text-neutral-500 mt-1">Hasil Scoring BANT</p>
      </div>

      {/* Score Card */}
      <div
        className={`rounded-lg border p-6 ${
          isPass ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"
        }`}
      >
        <div className="text-center">
          <p className={`text-4xl font-bold ${isPass ? "text-green-600" : "text-red-600"}`}>
            {result.bant_score}
            <span className="text-lg font-normal text-neutral-400">/100</span>
          </p>
          <p className={`text-sm font-medium mt-1 ${isPass ? "text-green-700" : "text-red-700"}`}>
            {isPass ? "Lolos Threshold — Masuk Antrian Assignment" : "Perlu Klarifikasi Tambahan"}
          </p>
        </div>

        {/* Detail per kriteria */}
        <div className="grid grid-cols-2 gap-3 mt-4">
          {(["budget", "authority", "need", "timeline"] as const).map((key) => (
            <div key={key} className="bg-white rounded-md p-3 border border-neutral-100">
              <p className="text-xs text-neutral-500 capitalize">{key}</p>
              <p className="text-lg font-semibold text-neutral-800">
                {result.sub_scores?.[key] ?? 0}
                <span className="text-xs font-normal text-neutral-400">/25</span>
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Status perubahan */}
      <div className="bg-white rounded-lg border border-neutral-200 p-4">
        <p className="text-sm text-neutral-600">
          <span className="font-medium">Status proyek diubah:</span>{" "}
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
              isPass
                ? "bg-blue-100 text-blue-700"
                : "bg-yellow-100 text-yellow-700"
            }`}
          >
            {result.status}
          </span>
        </p>

        {result.feedback && (
          <pre className="mt-3 whitespace-pre-wrap text-xs text-neutral-600 font-sans">
            {result.feedback}
          </pre>
        )}
      </div>

      {/* Action button */}
      <button
        onClick={onViewProject}
        className="w-full py-3 px-4 rounded-lg font-medium text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800 transition-all duration-200 min-h-touch"
      >
        Lihat Detail Proyek
      </button>
    </div>
  );
}
