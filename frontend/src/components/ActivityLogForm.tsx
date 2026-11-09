"use client";

import { useState, useCallback, useMemo } from "react";
import { apiRequest } from "@/lib/fetcher";

/**
 * Form untuk mencatat Activity Log
 *
 * Field:
 * - Jenis aktivitas (work_type): Project / Non-Project
 * - Proyek (dropdown, hanya untuk Project)
 * - Fase proyek (project_phase, hanya untuk Project; default dari status proyek)
 * - Kategori subtask (dropdown, tergantung work_type)
 * - Durasi (0.25–24 jam, step 0.25)
 * - Catatan (textarea max 5000 karakter)
 *
 * Requirements: 8.1, 8.5
 */

// Sub-kategori per work_type — selaras dengan backend schemas/activity_log.py
const PROJECT_SUBTASK_CATEGORIES = [
  "Assessment",
  "Internal Meeting",
  "Customer Meeting",
  "Principal Meeting",
  "Commercial Document",
  "Technical Document",
  "Document Review",
] as const;

const NON_PROJECT_SUBTASK_CATEGORIES = [
  "Training",
  "Self-Lab",
  "Self-Learning",
  "Exam",
  "Internal Meeting",
  "Internal Presentation",
  "External Presentation",
  "Principal Meeting",
] as const;

const PROJECT_PHASES = [
  "Pre-Implementation",
  "Implementation",
  "Post-Implementation",
] as const;

type WorkType = "Project" | "Non-Project";
type ProjectPhase = (typeof PROJECT_PHASES)[number];

/** Default fase dari status proyek — selaras dengan backend default_phase_for_status */
function defaultPhaseForStatus(status?: string): ProjectPhase {
  return status === "Handover Complete" ? "Implementation" : "Pre-Implementation";
}

interface Project {
  id: string;
  project_name: string;
  status?: string;
}

interface ActionItem {
  description: string;
  pic?: string | null;
}

interface AiPolishedNotes {
  discussion_points: string[];
  action_items: ActionItem[];
}

interface ActivityLogFormProps {
  /** Daftar proyek yang tersedia untuk dipilih */
  projects: Project[];
  /** Callback setelah berhasil submit */
  onSuccess?: () => void;
  /** ID proyek yang dipilih otomatis (mis. dari ?project=) */
  defaultProjectId?: string;
}

interface FormErrors {
  id_project?: string;
  project_phase?: string;
  subtask_category?: string;
  duration_hours?: string;
  raw_notes?: string;
}

const MAX_NOTES_LENGTH = 5000;

export function ActivityLogForm({ projects, onSuccess, defaultProjectId }: ActivityLogFormProps) {
  const defaultProject = projects.find((p) => p.id === defaultProjectId);
  const [workType, setWorkType] = useState<WorkType>("Project");
  const [idProject, setIdProject] = useState(defaultProject?.id ?? "");
  const [projectPhase, setProjectPhase] = useState<ProjectPhase>(
    defaultPhaseForStatus(defaultProject?.status)
  );
  const [category, setCategory] = useState("");
  const [duration, setDuration] = useState<string>("1");
  const [rawNotes, setRawNotes] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [polishedNotes, setPolishedNotes] = useState<AiPolishedNotes | null>(null);

  // Daftar subtask sesuai work_type aktif
  const availableCategories = useMemo(
    () =>
      workType === "Non-Project"
        ? NON_PROJECT_SUBTASK_CATEGORIES
        : PROJECT_SUBTASK_CATEGORIES,
    [workType]
  );

  // Auto-dismiss toast setelah 3 detik
  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  }, []);

  /** Ganti work_type — reset field yang tidak relevan + sesuaikan subtask */
  const handleWorkTypeChange = useCallback((wt: WorkType) => {
    setWorkType(wt);
    setCategory(""); // subtask set berubah, reset pilihan
    setErrors({});
    if (wt === "Non-Project") {
      setIdProject("");
    }
  }, []);

  /** Saat memilih proyek, set default fase dari status proyek */
  const handleProjectChange = useCallback(
    (projectId: string) => {
      setIdProject(projectId);
      const proj = projects.find((p) => p.id === projectId);
      setProjectPhase(defaultPhaseForStatus(proj?.status));
      if (errors.id_project) setErrors((prev) => ({ ...prev, id_project: undefined }));
    },
    [projects, errors.id_project]
  );

  /**
   * Validasi form sebelum submit
   */
  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (workType === "Project") {
      if (!idProject) newErrors.id_project = "Proyek wajib dipilih";
      if (!projectPhase) newErrors.project_phase = "Fase wajib dipilih";
    }
    if (!category) {
      newErrors.subtask_category = "Subtask wajib dipilih";
    }

    const dur = parseFloat(duration);
    if (isNaN(dur) || dur < 0.25 || dur > 24) {
      newErrors.duration_hours = "Durasi harus antara 0.25 - 24 jam";
    }

    if (!rawNotes.trim()) {
      newErrors.raw_notes = "Catatan tidak boleh kosong";
    } else if (rawNotes.length > MAX_NOTES_LENGTH) {
      newErrors.raw_notes = `Catatan maksimal ${MAX_NOTES_LENGTH} karakter`;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [workType, idProject, projectPhase, category, duration, rawNotes]);

  /**
   * Handle submit form — POST ke /api/v1/activity-logs
   */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!validate()) return;

      setIsSubmitting(true);
      try {
        const body: Record<string, unknown> = {
          work_type: workType,
          subtask_category: category,
          duration_hours: parseFloat(duration),
          raw_notes: rawNotes.trim(),
        };
        if (workType === "Project") {
          body.id_project = idProject;
          body.project_phase = projectPhase;
        }

        const result = await apiRequest<{ ai_polished_notes?: AiPolishedNotes }>("/activity-logs", {
          method: "POST",
          body,
        });

        // Tampilkan action items dari AI polishing jika ada
        if (result.ai_polished_notes?.action_items?.length) {
          setPolishedNotes(result.ai_polished_notes);
        } else {
          setPolishedNotes(null);
        }

        showToast("success", "Activity log berhasil disimpan");
        // Reset form
        setWorkType("Project");
        setIdProject(defaultProject?.id ?? "");
        setProjectPhase(defaultPhaseForStatus(defaultProject?.status));
        setCategory("");
        setDuration("1");
        setRawNotes("");
        setErrors({});
        onSuccess?.();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Gagal menyimpan activity log";
        showToast("error", message);
      } finally {
        setIsSubmitting(false);
      }
    },
    [workType, idProject, projectPhase, category, duration, rawNotes, validate, onSuccess, showToast, defaultProject]
  );

  const inputClass = (hasError: boolean) =>
    `w-full px-3 py-2.5 border rounded-lg text-sm
     focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
     disabled:opacity-50 disabled:bg-neutral-100
     ${hasError ? "border-red-300 bg-red-50" : "border-neutral-300"}`;

  return (
    <div className="relative">
      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all duration-300 ${
            toast.type === "success"
              ? "bg-green-50 text-green-800 border border-green-200"
              : "bg-red-50 text-red-800 border border-red-200"
          }`}
          role="alert"
        >
          {toast.message}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" aria-label="Form activity log">
        {/* Jenis aktivitas (work_type) */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 mb-1">
            Jenis Aktivitas <span className="text-red-500">*</span>
          </label>
          <div className="flex gap-2">
            {(["Project", "Non-Project"] as WorkType[]).map((wt) => (
              <button
                key={wt}
                type="button"
                onClick={() => handleWorkTypeChange(wt)}
                disabled={isSubmitting}
                className={`flex-1 px-3 py-2.5 text-sm font-medium rounded-lg border transition-colors min-h-[44px] ${
                  workType === wt
                    ? "bg-primary-50 text-primary-700 border-primary-300"
                    : "bg-white text-neutral-600 border-neutral-300 hover:bg-neutral-50"
                }`}
              >
                {wt}
              </button>
            ))}
          </div>
        </div>

        {/* Proyek + Fase (hanya untuk Project) */}
        {workType === "Project" && (
          <>
            <div>
              <label htmlFor="log-project" className="block text-sm font-medium text-neutral-700 mb-1">
                Proyek <span className="text-red-500">*</span>
              </label>
              <select
                id="log-project"
                value={idProject}
                onChange={(e) => handleProjectChange(e.target.value)}
                disabled={isSubmitting}
                className={inputClass(!!errors.id_project)}
                aria-invalid={!!errors.id_project}
              >
                <option value="">Pilih proyek...</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.project_name}
                  </option>
                ))}
              </select>
              {errors.id_project && (
                <p className="text-xs text-red-600 mt-1" role="alert">{errors.id_project}</p>
              )}
            </div>

            <div>
              <label htmlFor="log-phase" className="block text-sm font-medium text-neutral-700 mb-1">
                Fase Proyek <span className="text-red-500">*</span>
              </label>
              <select
                id="log-phase"
                value={projectPhase}
                onChange={(e) => setProjectPhase(e.target.value as ProjectPhase)}
                disabled={isSubmitting}
                className={inputClass(!!errors.project_phase)}
              >
                {PROJECT_PHASES.map((ph) => (
                  <option key={ph} value={ph}>{ph}</option>
                ))}
              </select>
              <p className="text-xs text-neutral-400 mt-1">
                Default dari status proyek — ubah bila aktivitas berada di fase berbeda.
              </p>
            </div>
          </>
        )}

        {/* Subtask (tergantung work_type) */}
        <div>
          <label htmlFor="log-category" className="block text-sm font-medium text-neutral-700 mb-1">
            Subtask <span className="text-red-500">*</span>
          </label>
          <select
            id="log-category"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              if (errors.subtask_category) setErrors((prev) => ({ ...prev, subtask_category: undefined }));
            }}
            disabled={isSubmitting}
            className={inputClass(!!errors.subtask_category)}
            aria-invalid={!!errors.subtask_category}
          >
            <option value="">Pilih subtask...</option>
            {availableCategories.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
          {errors.subtask_category && (
            <p className="text-xs text-red-600 mt-1" role="alert">{errors.subtask_category}</p>
          )}
        </div>

        {/* Durasi */}
        <div>
          <label htmlFor="log-duration" className="block text-sm font-medium text-neutral-700 mb-1">
            Durasi (jam) <span className="text-red-500">*</span>
          </label>
          <input
            id="log-duration"
            type="number"
            min="0.25"
            max="24"
            step="0.25"
            value={duration}
            onChange={(e) => {
              setDuration(e.target.value);
              if (errors.duration_hours) setErrors((prev) => ({ ...prev, duration_hours: undefined }));
            }}
            disabled={isSubmitting}
            className={inputClass(!!errors.duration_hours)}
            aria-invalid={!!errors.duration_hours}
          />
          {errors.duration_hours && (
            <p className="text-xs text-red-600 mt-1" role="alert">{errors.duration_hours}</p>
          )}
        </div>

        {/* Catatan */}
        <div>
          <label htmlFor="log-notes" className="block text-sm font-medium text-neutral-700 mb-1">
            Catatan <span className="text-red-500">*</span>
          </label>
          <textarea
            id="log-notes"
            value={rawNotes}
            onChange={(e) => {
              setRawNotes(e.target.value);
              if (errors.raw_notes) setErrors((prev) => ({ ...prev, raw_notes: undefined }));
            }}
            disabled={isSubmitting}
            maxLength={MAX_NOTES_LENGTH}
            rows={4}
            placeholder="Tuliskan catatan aktivitas..."
            className={`${inputClass(!!errors.raw_notes)} resize-none`}
            aria-invalid={!!errors.raw_notes}
          />
          <div className="flex justify-between items-center mt-1">
            {errors.raw_notes ? (
              <p className="text-xs text-red-600" role="alert">{errors.raw_notes}</p>
            ) : (
              <span />
            )}
            <p className={`text-xs ${rawNotes.length > MAX_NOTES_LENGTH ? "text-red-600" : "text-neutral-400"}`}>
              {rawNotes.length}/{MAX_NOTES_LENGTH}
            </p>
          </div>
        </div>

        {/* Tombol Submit */}
        <button
          type="submit"
          disabled={isSubmitting}
          className={`w-full py-2.5 px-4 rounded-lg font-medium text-white 
            transition-all duration-200 min-h-[44px]
            ${isSubmitting
              ? "bg-neutral-400 cursor-not-allowed"
              : "bg-primary-600 hover:bg-primary-700 active:bg-primary-800"
            }`}
        >
          {isSubmitting ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Menyimpan...
            </span>
          ) : (
            "Simpan Activity Log"
          )}
        </button>
      </form>

      {/* Action Items dari AI polishing */}
      {polishedNotes && polishedNotes.action_items.length > 0 && (
        <div className="mt-5 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">Action Items</h3>
          <ul className="space-y-1.5">
            {polishedNotes.action_items.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2 text-sm text-amber-900">
                <span className="text-amber-500 mt-0.5">•</span>
                <span>
                  {item.description}
                  {item.pic && (
                    <span className="text-amber-600 ml-1">(PIC: {item.pic})</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <button
            onClick={() => setPolishedNotes(null)}
            className="mt-3 text-xs text-amber-600 hover:text-amber-800 underline"
          >
            Tutup
          </button>
        </div>
      )}
    </div>
  );
}
