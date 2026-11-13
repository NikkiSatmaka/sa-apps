"use client";

import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "./LoadError";
import { useAuthStore } from "@/store/auth";

/**
 * Section Kolaborator — Menampilkan dan mengelola kolaborator proyek.
 * SA maupun Sales bisa menambahkan peer atau atasan sebagai viewer atau contributor.
 */

interface Collaborator {
  id: string;
  user_id: string;
  user_name: string;
  user_email: string;
  user_role: string;
  role: "viewer" | "contributor";
  added_by_name: string;
  created_at: string;
}

interface UserSearchResult {
  id: string;
  name: string;
  email: string;
  role: string;
}

interface CollaboratorSectionProps {
  projectId: string;
  initialCollaborators?: Collaborator[];
  onMutate?: () => void;
}

export function CollaboratorSection({
  projectId,
  initialCollaborators,
  onMutate,
}: CollaboratorSectionProps) {
  const { user } = useAuthStore();
  const [showAddForm, setShowAddForm] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedUser, setSelectedUser] = useState<UserSearchResult | null>(null);
  const [selectedRole, setSelectedRole] = useState<"viewer" | "contributor">("viewer");
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  // Fetch collaborators
  const { data, mutate, error: listError } = useSWR<{ items: Collaborator[]; total: number }>(
    `/projects/${projectId}/collaborators`,
    fetcher
  );

  const collaborators = data?.items ?? initialCollaborators ?? [];
  // Gagal memuat dan belum ada data dari server: tampilkan error, bukan keadaan kosong.
  const gagalMemuat = Boolean(listError) && !data;

  // Search users
  const {
    data: searchResultsRaw,
    error: searchError,
    mutate: mutateSearch,
  } = useSWR<UserSearchResult[]>(
    searchQuery.length >= 2 ? `/projects/users/search?q=${encodeURIComponent(searchQuery)}&limit=10` : null,
    fetcher
  );

  // Batasi kandidat sesuai aturan role penambah (selaras dengan backend):
  // - Sales hanya bisa menambahkan sesama Sales
  // - SA hanya bisa menambahkan sesama SA
  // - Lead_SA / Admin bisa menambahkan role apa pun
  const searchResults = (searchResultsRaw ?? []).filter((u) => {
    if (user?.role === "Sales") return u.role === "Sales";
    if (user?.role === "SA") return u.role === "SA";
    return true; // Lead_SA / Admin
  });

  // Keterangan batasan untuk ditampilkan di form
  const addRestrictionNote =
    user?.role === "Sales"
      ? "Sebagai Sales, Anda hanya dapat menambahkan sesama Sales."
      : user?.role === "SA"
        ? "Sebagai SA, Anda hanya dapat menambahkan sesama SA."
        : null;

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSelectedUser(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleAdd = async () => {
    if (!selectedUser) return;
    setIsAdding(true);
    setError(null);

    try {
      await apiRequest(`/projects/${projectId}/collaborators`, {
        method: "POST",
        body: { user_id: selectedUser.id, role: selectedRole },
      });
      setShowAddForm(false);
      setSearchQuery("");
      setSelectedUser(null);
      setSelectedRole("viewer");
      mutate();
      onMutate?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Gagal menambahkan kolaborator";
      setError(msg);
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (userId: string, userName: string) => {
    if (!confirm(`Hapus ${userName} dari kolaborator proyek ini?`)) return;

    try {
      await apiRequest(`/projects/${projectId}/collaborators/${userId}`, {
        method: "DELETE",
      });
      mutate();
      onMutate?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Gagal menghapus kolaborator";
      setError(msg);
    }
  };

  // Can add collaborator: SA, Sales, Lead_SA, Admin
  const canManage = user?.role && ["SA", "Sales", "Lead_SA", "Admin"].includes(user.role);

  const getRoleBadge = (role: string) => {
    if (role === "viewer")
      return "bg-blue-50 text-blue-700 border-blue-200";
    return "bg-emerald-50 text-emerald-700 border-emerald-200";
  };

  const getRoleLabel = (role: string) => {
    if (role === "viewer") return "Viewer";
    return "Contributor";
  };

  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-neutral-700">Kolaborator</h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            Peer atau atasan yang di-tag untuk melihat atau berkontribusi di proyek ini
          </p>
        </div>
        {canManage && (
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="px-3 py-1.5 text-xs font-medium text-primary-600 border border-primary-200
                       rounded-lg hover:bg-primary-50 transition-colors min-h-[32px]"
          >
            {showAddForm ? "Batal" : "+ Tambah"}
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Add form */}
      {showAddForm && (
        <div ref={searchRef} className="mb-4 p-3 bg-neutral-50 rounded-lg border border-neutral-200 space-y-3">
          {/* Keterangan batasan role */}
          {addRestrictionNote && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2 py-1.5">
              {addRestrictionNote}
            </p>
          )}

          {/* Search user */}
          <div className="relative">
            <label className="text-xs font-medium text-neutral-600 mb-1 block">
              Cari user (nama atau email):
            </label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setSelectedUser(null);
              }}
              placeholder="Ketik minimal 2 karakter..."
              className="w-full px-3 py-2 text-sm border border-neutral-300 rounded-lg
                         focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
            />

            {/* Pencarian gagal: bedakan dari "tidak ada yang cocok" */}
            {searchQuery.length >= 2 && !selectedUser && searchError && !searchResultsRaw && (
              <LoadError
                className="mt-1"
                message="Gagal mencari user."
                onRetry={() => mutateSearch()}
              />
            )}

            {/* Tidak ada kandidat yang cocok setelah filter role */}
            {searchQuery.length >= 2 && !selectedUser && !searchError && searchResults.length === 0 && (
              <p className="mt-1 text-xs text-neutral-400">
                Tidak ada user yang cocok dan diizinkan untuk ditambahkan.
              </p>
            )}

            {/* Search results dropdown */}
            {searchResults.length > 0 && !selectedUser && (
              <div className="absolute z-10 w-full mt-1 bg-white border border-neutral-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {searchResults.map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => {
                      setSelectedUser(u);
                      setSearchQuery(u.name);
                      // Auto-set contributor only if user is SA
                      if (u.role !== "SA" && u.role !== "Lead_SA" && u.role !== "Admin") {
                        setSelectedRole("viewer");
                      }
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-neutral-50
                               border-b border-neutral-100 last:border-b-0"
                  >
                    <div className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center shrink-0">
                      <span className="text-xs font-medium text-primary-600">
                        {u.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-neutral-800 truncate">{u.name}</p>
                      <p className="text-xs text-neutral-500 truncate">{u.email}</p>
                    </div>
                    <span className="px-1.5 py-0.5 text-xs bg-neutral-100 text-neutral-600 rounded">
                      {u.role}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selected user display */}
          {selectedUser && (
            <div className="flex items-center gap-2 p-2 bg-primary-50 border border-primary-200 rounded-lg">
              <div className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center shrink-0">
                <span className="text-xs font-medium text-primary-600">
                  {selectedUser.name.charAt(0).toUpperCase()}
                </span>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-neutral-800">{selectedUser.name}</p>
                <p className="text-xs text-neutral-500">{selectedUser.email} — {selectedUser.role}</p>
              </div>
              <button
                onClick={() => { setSelectedUser(null); setSearchQuery(""); }}
                className="text-xs text-neutral-500 hover:text-neutral-700"
              >
                ✕
              </button>
            </div>
          )}

          {/* Role selection */}
          <div>
            <label className="text-xs font-medium text-neutral-600 mb-1 block">Peran:</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setSelectedRole("viewer")}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                  selectedRole === "viewer"
                    ? "bg-blue-50 text-blue-700 border-blue-300"
                    : "bg-white text-neutral-600 border-neutral-300 hover:bg-neutral-50"
                }`}
              >
                👁 Viewer — Bisa melihat proyek
              </button>
              <button
                type="button"
                onClick={() => setSelectedRole("contributor")}
                disabled={selectedUser?.role === "Sales"}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                  selectedRole === "contributor"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                    : "bg-white text-neutral-600 border-neutral-300 hover:bg-neutral-50"
                } ${selectedUser?.role === "Sales" ? "opacity-50 cursor-not-allowed" : ""}`}
                title={selectedUser?.role === "Sales" ? "Hanya SA yang bisa menjadi contributor" : ""}
              >
                ✏️ Contributor — Bisa tambah Activity Log
              </button>
            </div>
          </div>

          {/* Submit */}
          <button
            onClick={handleAdd}
            disabled={!selectedUser || isAdding}
            className="w-full px-3 py-2 text-sm font-medium text-white bg-primary-600
                       rounded-lg hover:bg-primary-700 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAdding ? "Menambahkan..." : "Tambah Kolaborator"}
          </button>
        </div>
      )}

      {/* Gagal memuat daftar: tampil di atas daftar awal (bila ada) atau menggantikan keadaan kosong */}
      {gagalMemuat && (
        <LoadError
          className="mb-3"
          message="Gagal memuat daftar kolaborator."
          onRetry={() => mutate()}
        />
      )}

      {/* List collaborators */}
      {collaborators.length === 0 ? (
        !gagalMemuat && (
          <p className="text-sm text-neutral-500 text-center py-3">
            Belum ada kolaborator di proyek ini.
          </p>
        )
      ) : (
        <div className="space-y-2">
          {collaborators.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-3 p-2.5 bg-neutral-50 rounded-lg"
            >
              <div className="w-8 h-8 rounded-full bg-neutral-200 flex items-center justify-center shrink-0">
                <span className="text-xs font-medium text-neutral-600">
                  {c.user_name.charAt(0).toUpperCase()}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-neutral-800 truncate">{c.user_name}</p>
                <p className="text-xs text-neutral-500 truncate">
                  {c.user_email} · <span className="text-neutral-400">{c.user_role}</span>
                </p>
              </div>
              <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${getRoleBadge(c.role)}`}>
                {getRoleLabel(c.role)}
              </span>
              {canManage && (
                <button
                  onClick={() => handleRemove(c.user_id, c.user_name)}
                  className="p-1 text-neutral-400 hover:text-red-600 transition-colors"
                  title="Hapus kolaborator"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
