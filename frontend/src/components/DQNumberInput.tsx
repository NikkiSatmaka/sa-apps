"use client";

import { useState, useCallback } from "react";
import { useAuthStore } from "@/store/auth";
import { isPrivileged, isRequesterTerbatas } from "@/lib/roles";

/**
 * Komponen input DQ Number dengan validasi format
 *
 * Fitur:
 * - Validasi regex: alfanumerik + hyphen, 5-20 karakter
 * - Real-time feedback validasi
 * - Submit button dengan loading state
 * - Disabled saat DQ sudah diset dan user adalah Sales
 * - Tampilkan nilai DQ saat ini jika sudah ada
 *
 * Requirements: 6.1, 6.2, 6.5, 6.6
 */

// Regex validasi: alfanumerik dan hyphen, panjang 5-20
const DQ_NUMBER_REGEX = /^[a-zA-Z0-9-]{5,20}$/;

interface DQNumberInputProps {
  /** Nilai DQ Number saat ini (null jika belum diset) */
  currentValue: string | null;
  /** Callback saat DQ Number disubmit */
  onSubmit: (dqNumber: string) => Promise<void>;
  /** Status loading */
  isSubmitting?: boolean;
}

export function DQNumberInput({
  currentValue,
  onSubmit,
  isSubmitting = false,
}: DQNumberInputProps) {
  const { user } = useAuthStore();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  // Sales/Product (bukan privileged) tidak bisa mengubah DQ yang sudah diset
  const isSalesWithDQ = isRequesterTerbatas(user) && currentValue !== null;
  // Lead SA dan admin boleh edit DQ yang sudah diset
  const canEdit = !currentValue || isPrivileged(user);

  /**
   * Validasi format DQ Number secara real-time
   */
  const validateDQNumber = useCallback((input: string): string | null => {
    if (!input.trim()) {
      return "DQ Number wajib diisi";
    }
    if (input.length < 5) {
      return "DQ Number minimal 5 karakter";
    }
    if (input.length > 20) {
      return "DQ Number maksimal 20 karakter";
    }
    if (!DQ_NUMBER_REGEX.test(input)) {
      return "Format DQ Number tidak valid (alfanumerik dan tanda hubung saja)";
    }
    return null;
  }, []);

  /**
   * Handle perubahan input
   */
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setValue(newValue);

      // Validasi real-time hanya setelah field pernah di-focus
      if (touched) {
        setError(validateDQNumber(newValue));
      }
    },
    [touched, validateDQNumber]
  );

  /**
   * Handle blur — mulai validasi real-time
   */
  const handleBlur = useCallback(() => {
    setTouched(true);
    setError(validateDQNumber(value));
  }, [value, validateDQNumber]);

  /**
   * Handle submit DQ Number
   */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      const validationError = validateDQNumber(value);
      if (validationError) {
        setError(validationError);
        setTouched(true);
        return;
      }

      await onSubmit(value.trim());
      setValue("");
      setTouched(false);
      setError(null);
    },
    [value, validateDQNumber, onSubmit]
  );

  // Tampilkan DQ Number yang sudah diset (read-only untuk Sales)
  if (currentValue && isSalesWithDQ) {
    return (
      <div className="space-y-2" aria-label="DQ Number tersimpan">
        <label className="block text-sm font-medium text-neutral-700">
          DQ Number
        </label>
        <div className="flex items-center gap-3">
          <div className="flex-1 px-3 py-2.5 bg-neutral-50 border border-neutral-200 rounded-lg">
            <span className="text-sm font-mono text-neutral-800">
              {currentValue}
            </span>
          </div>
          <span className="text-xs text-neutral-500 shrink-0">
            Tersimpan ✓
          </span>
        </div>
        <p className="text-xs text-neutral-400">
          DQ Number sudah diset. Hanya Lead SA yang dapat mengubahnya.
        </p>
      </div>
    );
  }

  // Tampilkan DQ Number yang sudah diset + opsi edit (untuk Lead SA)
  if (currentValue && canEdit) {
    return (
      <div className="space-y-3" aria-label="DQ Number input">
        <label className="block text-sm font-medium text-neutral-700">
          DQ Number
        </label>

        {/* Nilai saat ini */}
        <div className="flex items-center gap-2 px-3 py-2 bg-green-50 border border-green-200 rounded-lg">
          <svg className="w-4 h-4 text-green-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
          <span className="text-sm font-mono text-green-800">{currentValue}</span>
        </div>

        {/* Form edit */}
        <form onSubmit={handleSubmit} className="space-y-2">
          <p className="text-xs text-neutral-500">Ubah DQ Number:</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={value}
              onChange={handleChange}
              onBlur={handleBlur}
              disabled={isSubmitting}
              placeholder="Masukkan DQ Number baru"
              maxLength={20}
              className={`
                flex-1 px-3 py-2.5 border rounded-lg text-sm font-mono
                focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                disabled:opacity-50 disabled:bg-neutral-100
                ${error && touched ? "border-red-300 bg-red-50" : "border-neutral-300"}
              `}
              aria-invalid={!!(error && touched)}
              aria-describedby={error && touched ? "dq-edit-error" : undefined}
            />
            <button
              type="submit"
              disabled={isSubmitting || !value.trim()}
              className="px-4 py-2.5 rounded-lg font-medium text-white 
                         bg-primary-600 hover:bg-primary-700 active:bg-primary-800
                         transition-colors duration-100 min-w-[44px] min-h-[44px]
                         disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Simpan DQ Number baru"
            >
              {isSubmitting ? (
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                "Ubah"
              )}
            </button>
          </div>
          {error && touched && (
            <p id="dq-edit-error" className="text-xs text-red-600" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    );
  }

  // Form input DQ Number baru (belum pernah diset)
  return (
    <form onSubmit={handleSubmit} className="space-y-2" aria-label="Input DQ Number">
      <label
        htmlFor="dq-number-input"
        className="block text-sm font-medium text-neutral-700"
      >
        DQ Number <span className="text-red-500">*</span>
      </label>
      <p className="text-xs text-neutral-500 mb-2">
        Masukkan nomor Deal Qualification (alfanumerik + tanda hubung, 5-20 karakter)
      </p>

      <div className="flex gap-2">
        <input
          id="dq-number-input"
          type="text"
          value={value}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSubmitting}
          placeholder="Contoh: DQ-2024-001"
          maxLength={20}
          className={`
            flex-1 px-3 py-2.5 border rounded-lg text-sm font-mono
            focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
            disabled:opacity-50 disabled:bg-neutral-100
            ${error && touched ? "border-red-300 bg-red-50" : "border-neutral-300"}
          `}
          aria-invalid={!!(error && touched)}
          aria-describedby={error && touched ? "dq-number-error" : "dq-number-hint"}
        />
        <button
          type="submit"
          disabled={isSubmitting || !value.trim()}
          className="px-4 py-2.5 rounded-lg font-medium text-white 
                     bg-primary-600 hover:bg-primary-700 active:bg-primary-800
                     transition-colors duration-100 min-w-[44px] min-h-[44px]
                     disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="Simpan DQ Number"
        >
          {isSubmitting ? (
            <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            "Simpan"
          )}
        </button>
      </div>

      {/* Feedback validasi */}
      {error && touched ? (
        <p id="dq-number-error" className="text-xs text-red-600" role="alert">
          {error}
        </p>
      ) : (
        <p id="dq-number-hint" className="text-xs text-neutral-400">
          {value.length > 0 && `${value.length}/20 karakter`}
        </p>
      )}

      {/* Indikator validitas real-time */}
      {value.length > 0 && !error && touched && (
        <p className="text-xs text-green-600 flex items-center gap-1">
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
          Format valid
        </p>
      )}
    </form>
  );
}
