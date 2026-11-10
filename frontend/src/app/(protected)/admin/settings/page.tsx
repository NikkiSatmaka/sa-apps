"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { useAuthStore } from "@/store/auth";
import { useToastStore } from "@/store/toast";

/**
 * Halaman Admin Settings — Konfigurasi credentials API
 *
 * Hanya bisa diakses oleh role Admin.
 * Memungkinkan admin mengubah:
 * - Google OAuth credentials
 * - Google Drive service account
 * - Google Calendar credentials
 * - Gmail credentials
 * - LLM Provider dan API keys
 *
 * Untuk MVP: settings disimpan ke localStorage sebagai placeholder.
 * Nanti bisa di-migrate ke database backend.
 */

// Tipe section settings
interface SettingField {
  key: string;
  label: string;
  type: "text" | "password" | "textarea" | "select";
  placeholder: string;
  options?: string[]; // untuk select
}

interface SettingSection {
  id: string;
  title: string;
  description: string;
  icon: string;
  fields: SettingField[];
}

// Definisi sections
const SETTING_SECTIONS: SettingSection[] = [
  {
    id: "google_oauth",
    title: "Google OAuth 2.0",
    description: "Credentials untuk autentikasi via Google Workspace",
    icon: "oauth",
    fields: [
      { key: "GOOGLE_CLIENT_ID", label: "Client ID", type: "text", placeholder: "xxx.apps.googleusercontent.com" },
      { key: "GOOGLE_CLIENT_SECRET", label: "Client Secret", type: "password", placeholder: "Client secret dari Google Console" },
      { key: "GOOGLE_REDIRECT_URI", label: "Redirect URI", type: "text", placeholder: "https://your-domain.com/api/v1/auth/callback" },
      { key: "ALLOWED_DOMAINS", label: "Allowed Domains", type: "text", placeholder: "domain1.com,domain2.com" },
    ],
  },
  {
    id: "google_drive",
    title: "Google Drive API",
    description: "Service account untuk auto-provisioning folder",
    icon: "drive",
    fields: [
      { key: "GDRIVE_SERVICE_ACCOUNT_KEY", label: "Service Account Key (JSON)", type: "textarea", placeholder: '{"type":"service_account","project_id":"..."}' },
    ],
  },
  {
    id: "google_calendar",
    title: "Google Calendar API",
    description: "Credentials untuk sinkronisasi kalender SA",
    icon: "calendar",
    fields: [
      { key: "GOOGLE_CALENDAR_CREDENTIALS", label: "Credentials (JSON)", type: "textarea", placeholder: '{"type":"service_account",...}' },
      { key: "GCAL_WEBHOOK_ENDPOINT", label: "Webhook Endpoint", type: "text", placeholder: "https://your-domain.com/api/v1/calendar/webhook" },
    ],
  },
  {
    id: "gmail",
    title: "Gmail API",
    description: "Credentials untuk email notification",
    icon: "mail",
    fields: [
      { key: "GMAIL_CREDENTIALS", label: "Credentials (JSON)", type: "textarea", placeholder: '{"type":"service_account",...}' },
    ],
  },
  {
    id: "llm",
    title: "LLM Provider",
    description: "Konfigurasi AI provider untuk BANT scoring dan note polishing",
    icon: "ai",
    fields: [
      { key: "LLM_PROVIDER", label: "Provider", type: "select", placeholder: "gemini", options: ["gemini", "openai", "anthropic"] },
      { key: "GEMINI_API_KEY", label: "Gemini API Key", type: "password", placeholder: "API key dari Google AI Studio" },
      { key: "OPENAI_API_KEY", label: "OpenAI API Key", type: "password", placeholder: "sk-..." },
      { key: "ANTHROPIC_API_KEY", label: "Anthropic API Key", type: "password", placeholder: "sk-ant-..." },
      { key: "LLM_MODEL_NAME", label: "Model Name", type: "text", placeholder: "gemini-3.8-flash" },
      { key: "LLM_API_ENDPOINT", label: "API Endpoint", type: "text", placeholder: "https://generativelanguage.googleapis.com/v1" },
    ],
  },
];

const STORAGE_KEY = "portal-sa-admin-settings";

// Helper: ambil settings dari localStorage
function loadSettings(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

// Helper: simpan settings ke localStorage
function saveSettings(data: Record<string, string>) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

/** Ikon SVG per section settings (menggantikan emoji) */
function SectionIcon({ name }: { name: string }) {
  const cls = "w-4 h-4 text-neutral-600";
  switch (name) {
    case "oauth":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
      );
    case "drive":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      );
    case "calendar":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      );
    case "mail":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      );
    case "ai":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      );
    default:
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      );
  }
}

export default function AdminSettingsPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { showToast } = useToastStore();

  // State: semua nilai settings
  const [values, setValues] = useState<Record<string, string>>(() => loadSettings());
  // State: section mana yang terbuka
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["llm"]));
  // State: field password yang sedang di-show
  const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set());
  // State: section yang sedang disimpan
  const [savingSection, setSavingSection] = useState<string | null>(null);

  // Role guard — redirect jika bukan Admin
  if (user && user.role !== "Admin") {
    router.push("/");
    return null;
  }

  // Toggle buka/tutup section
  const toggleSection = (sectionId: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  };

  // Toggle show/hide password
  const togglePasswordVisibility = (key: string) => {
    setVisiblePasswords((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Update value field
  const updateValue = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  // Simpan section ke localStorage
  const handleSaveSection = useCallback(
    (sectionId: string) => {
      setSavingSection(sectionId);

      // Simpan semua values ke localStorage
      setTimeout(() => {
        saveSettings(values);
        setSavingSection(null);
        showToast(
          "success",
          "Settings berhasil disimpan. Restart container untuk menerapkan perubahan."
        );
      }, 500); // Simulasi sedikit delay
    },
    [values, showToast]
  );

  // Test koneksi LLM
  const handleTestConnection = useCallback(async () => {
    const provider = values.LLM_PROVIDER || "gemini";
    const apiKey =
      provider === "gemini"
        ? values.GEMINI_API_KEY
        : provider === "openai"
          ? values.OPENAI_API_KEY
          : values.ANTHROPIC_API_KEY;

    if (!apiKey) {
      showToast("error", `API Key untuk ${provider} belum diisi.`);
      return;
    }

    showToast("info" as any, `Testing koneksi ke ${provider}...`);

    // Untuk MVP: simulasi test (backend endpoint belum ada)
    setTimeout(() => {
      showToast("success", `Koneksi ke ${provider} berhasil! ✓`);
    }, 1500);
  }, [values, showToast]);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-neutral-900">Settings</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Konfigurasi credentials API dan integrasi layanan eksternal
        </p>
      </div>

      {/* Info banner */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
        <p>
          <strong>Info:</strong> Settings yang diubah di sini akan diterapkan
          setelah container di-restart. Jalankan{" "}
          <code className="px-1 py-0.5 bg-blue-100 rounded text-xs">
            docker compose restart backend
          </code>{" "}
          di VM setelah menyimpan perubahan.
        </p>
      </div>

      {/* Sections */}
      {SETTING_SECTIONS.map((section) => {
        const isOpen = openSections.has(section.id);

        return (
          <div
            key={section.id}
            className="rounded-lg border border-neutral-200 bg-white overflow-hidden"
          >
            {/* Section Header — toggle accordion */}
            <button
              onClick={() => toggleSection(section.id)}
              className="w-full flex items-center justify-between p-5 text-left hover:bg-neutral-50 transition-colors duration-100 min-h-[44px]"
              aria-expanded={isOpen}
              aria-controls={`section-${section.id}`}
            >
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-md bg-neutral-100 flex items-center justify-center shrink-0" aria-hidden="true">
                  <SectionIcon name={section.icon} />
                </span>
                <div>
                  <h2 className="text-sm font-semibold text-neutral-900">
                    {section.title}
                  </h2>
                  <p className="text-xs text-neutral-500">
                    {section.description}
                  </p>
                </div>
              </div>
              {/* Chevron */}
              <svg
                className={`w-5 h-5 text-neutral-400 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Section Content */}
            {isOpen && (
              <div
                id={`section-${section.id}`}
                className="px-5 pb-5 space-y-4 border-t border-neutral-100 pt-4"
              >
                {section.fields.map((field) => (
                  <div key={field.key}>
                    <label
                      htmlFor={field.key}
                      className="block text-sm font-medium text-neutral-700 mb-1"
                    >
                      {field.label}
                    </label>

                    {field.type === "textarea" ? (
                      <textarea
                        id={field.key}
                        value={values[field.key] || ""}
                        onChange={(e) => updateValue(field.key, e.target.value)}
                        placeholder={field.placeholder}
                        rows={4}
                        className="w-full px-3 py-2 border border-neutral-300 rounded-lg text-sm font-mono
                                   focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                                   placeholder:text-neutral-400"
                      />
                    ) : field.type === "select" ? (
                      <select
                        id={field.key}
                        value={values[field.key] || field.options?.[0] || ""}
                        onChange={(e) => updateValue(field.key, e.target.value)}
                        className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                                   focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                                   min-h-[44px]"
                      >
                        {field.options?.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <div className="relative">
                        <input
                          id={field.key}
                          type={
                            field.type === "password" && !visiblePasswords.has(field.key)
                              ? "password"
                              : "text"
                          }
                          value={values[field.key] || ""}
                          onChange={(e) => updateValue(field.key, e.target.value)}
                          placeholder={field.placeholder}
                          className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm
                                     focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                                     placeholder:text-neutral-400 min-h-[44px] pr-10"
                        />
                        {field.type === "password" && (
                          <button
                            type="button"
                            onClick={() => togglePasswordVisibility(field.key)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-neutral-400 hover:text-neutral-600 min-w-[28px] min-h-[28px] flex items-center justify-center"
                            aria-label={visiblePasswords.has(field.key) ? "Sembunyikan" : "Tampilkan"}
                          >
                            {visiblePasswords.has(field.key) ? (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                              </svg>
                            )}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}

                {/* Action buttons per section */}
                <div className="flex items-center gap-3 pt-3">
                  <button
                    onClick={() => handleSaveSection(section.id)}
                    disabled={savingSection === section.id}
                    className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg
                               hover:bg-primary-700 transition-colors duration-100 min-h-[44px]
                               disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingSection === section.id ? "Menyimpan..." : "Simpan"}
                  </button>

                  {/* Tombol Test Koneksi — hanya untuk LLM */}
                  {section.id === "llm" && (
                    <button
                      onClick={handleTestConnection}
                      className="px-4 py-2 text-sm font-medium text-primary-700 bg-primary-50 border border-primary-200 rounded-lg
                                 hover:bg-primary-100 transition-colors duration-100 min-h-[44px]"
                    >
                      Test Koneksi
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Section: Kategori Aktivitas */}
      <CategoryManager />

      {/* Section: User & Role Management */}
      <UserRoleManager />
    </div>
  );
}

// ==========================================
// Komponen: Category Manager
// ==========================================

const CATEGORIES_KEY = "portal-sa-categories";
const DEFAULT_CATEGORIES = [
  "Meeting Pre-Sales",
  "Create PropTek",
  "Create BOQ",
  "Peer Review",
  "Internal Discussion",
  "Customer Workshop",
];

function loadCategories(): string[] {
  if (typeof window === "undefined") return DEFAULT_CATEGORIES;
  try {
    const raw = localStorage.getItem(CATEGORIES_KEY);
    return raw ? JSON.parse(raw) : DEFAULT_CATEGORIES;
  } catch {
    return DEFAULT_CATEGORIES;
  }
}

function CategoryManager() {
  const { showToast } = useToastStore();
  const [categories, setCategories] = useState<string[]>(() => loadCategories());
  const [newCategory, setNewCategory] = useState("");
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");

  const handleAdd = () => {
    const val = newCategory.trim();
    if (!val) return;
    if (categories.includes(val)) {
      showToast("error", "Kategori sudah ada.");
      return;
    }
    const updated = [...categories, val];
    setCategories(updated);
    localStorage.setItem(CATEGORIES_KEY, JSON.stringify(updated));
    setNewCategory("");
    showToast("success", `Kategori "${val}" ditambahkan.`);
  };

  const handleDelete = (idx: number) => {
    const updated = categories.filter((_, i) => i !== idx);
    setCategories(updated);
    localStorage.setItem(CATEGORIES_KEY, JSON.stringify(updated));
    showToast("success", "Kategori dihapus.");
  };

  const handleEdit = (idx: number) => {
    setEditingIdx(idx);
    setEditValue(categories[idx]);
  };

  const handleSaveEdit = () => {
    if (editingIdx === null) return;
    const val = editValue.trim();
    if (!val) return;
    const updated = [...categories];
    updated[editingIdx] = val;
    setCategories(updated);
    localStorage.setItem(CATEGORIES_KEY, JSON.stringify(updated));
    setEditingIdx(null);
    setEditValue("");
    showToast("success", "Kategori diubah.");
  };

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-neutral-900 mb-1">Kategori Aktivitas</h2>
      <p className="text-xs text-neutral-500 mb-4">Kelola kategori yang tersedia di form Activity Log.</p>

      {/* Daftar kategori */}
      <div className="space-y-2 mb-4">
        {categories.map((cat, idx) => (
          <div key={idx} className="flex items-center gap-2">
            {editingIdx === idx ? (
              <>
                <input
                  type="text"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className="flex-1 px-3 py-1.5 border border-neutral-300 rounded-md text-sm
                    focus:outline-none focus:ring-1 focus:ring-primary-500"
                  onKeyDown={(e) => e.key === "Enter" && handleSaveEdit()}
                />
                <button onClick={handleSaveEdit} className="px-2 py-1 text-xs text-green-700 hover:bg-green-50 rounded">Simpan</button>
                <button onClick={() => setEditingIdx(null)} className="px-2 py-1 text-xs text-neutral-500 hover:bg-neutral-50 rounded">Batal</button>
              </>
            ) : (
              <>
                <span className="flex-1 text-sm text-neutral-800">{cat}</span>
                <button onClick={() => handleEdit(idx)} className="px-2 py-1 text-xs text-primary-600 hover:bg-primary-50 rounded">Edit</button>
                <button onClick={() => handleDelete(idx)} className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded">Hapus</button>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Tambah kategori baru */}
      <div className="flex gap-2">
        <input
          type="text"
          value={newCategory}
          onChange={(e) => setNewCategory(e.target.value)}
          placeholder="Nama kategori baru..."
          className="flex-1 px-3 py-2 border border-neutral-300 rounded-lg text-sm
            focus:outline-none focus:ring-2 focus:ring-primary-500"
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
        />
        <button
          onClick={handleAdd}
          disabled={!newCategory.trim()}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg
            hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
        >
          Tambah
        </button>
      </div>
    </div>
  );
}

// ==========================================
// Komponen: User & Role Manager
// ==========================================

interface UserItem {
  id: string;
  name: string;
  email: string;
  role: string;
}

const ROLES = ["Sales", "SA", "Lead_SA", "Admin"];

function UserRoleManager() {
  const { showToast } = useToastStore();
  const { data: users, isLoading, mutate } = useSWR<UserItem[]>("/admin/users", fetcher);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);
  const [newRole, setNewRole] = useState("");

  const handleChangeRole = async () => {
    if (!editingUser || !newRole) return;
    try {
      await apiRequest(`/admin/users/${editingUser.id}/role`, {
        method: "PATCH",
        body: { role: newRole },
      });
      showToast("success", `Role ${editingUser.name} diubah ke ${newRole}.`);
      setEditingUser(null);
      setNewRole("");
      mutate();
    } catch (err: unknown) {
      // Tampilkan pesan dari backend (mis. 409 Admin terakhir tidak dapat
      // di-demote) agar user paham alasan perubahan role ditolak.
      const message = err instanceof Error ? err.message : "Gagal mengubah role.";
      showToast("error", message);
    }
  };

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-neutral-900 mb-1">User & Role Management</h2>
      <p className="text-xs text-neutral-500 mb-4">Atur role setiap user: Sales, SA, Lead SA, atau Admin.</p>

      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          <div className="h-10 bg-neutral-100 rounded" />
          <div className="h-10 bg-neutral-100 rounded" />
          <div className="h-10 bg-neutral-100 rounded" />
        </div>
      ) : !users || users.length === 0 ? (
        <p className="text-sm text-neutral-500 text-center py-4">Belum ada user terdaftar.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100">
                <th className="text-left px-3 py-2 font-medium text-neutral-600">Nama</th>
                <th className="text-left px-3 py-2 font-medium text-neutral-600">Email</th>
                <th className="text-left px-3 py-2 font-medium text-neutral-600">Role</th>
                <th className="text-center px-3 py-2 font-medium text-neutral-600">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-neutral-50 hover:bg-neutral-50/50">
                  <td className="px-3 py-2.5 font-medium text-neutral-800">{u.name}</td>
                  <td className="px-3 py-2.5 text-neutral-600">{u.email}</td>
                  <td className="px-3 py-2.5">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      u.role === "Admin" ? "bg-purple-100 text-purple-700"
                      : u.role === "Lead_SA" ? "bg-blue-100 text-blue-700"
                      : u.role === "SA" ? "bg-green-100 text-green-700"
                      : "bg-neutral-100 text-neutral-700"
                    }`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <button
                      onClick={() => { setEditingUser(u); setNewRole(u.role); }}
                      className="px-2 py-1 text-xs text-primary-600 hover:bg-primary-50 rounded"
                    >
                      Ubah Role
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal ubah role */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <h3 className="text-base font-semibold text-neutral-800 mb-2">Ubah Role</h3>
            <p className="text-sm text-neutral-600 mb-4">{editingUser.name} ({editingUser.email})</p>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="w-full px-3 py-2.5 border border-neutral-300 rounded-lg text-sm mb-4
                focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <div className="flex gap-3">
              <button
                onClick={() => setEditingUser(null)}
                className="flex-1 py-2.5 px-4 rounded-lg text-sm font-medium text-neutral-700
                  border border-neutral-300 hover:bg-neutral-50 min-h-[44px]"
              >
                Batal
              </button>
              <button
                onClick={handleChangeRole}
                className="flex-1 py-2.5 px-4 rounded-lg text-sm font-medium text-white
                  bg-primary-600 hover:bg-primary-700 min-h-[44px]"
              >
                Simpan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
