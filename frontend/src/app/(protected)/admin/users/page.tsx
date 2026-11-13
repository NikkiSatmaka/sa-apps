"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher, apiRequest } from "@/lib/fetcher";
import { LoadError } from "@/components/LoadError";
import { useAuthStore } from "@/store/auth";
import { useToastStore } from "@/store/toast";

/**
 * Halaman Pengguna (Admin) — daftar user dan ubah peran.
 *
 * Hanya bisa diakses oleh role Admin. Data dari `/admin/users`.
 */

interface UserItem {
  id: string;
  name: string;
  email: string;
  role: string;
}

const ROLES = ["Sales", "SA", "Lead_SA", "Admin"];

function UserRoleManager() {
  const { showToast } = useToastStore();
  const { data: users, isLoading, error, mutate } = useSWR<UserItem[]>("/admin/users", fetcher);
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
      ) : error && !users ? (
        <LoadError message="Gagal memuat daftar user." onRetry={() => mutate()} />
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

export default function AdminUsersPage() {
  const router = useRouter();
  const { user } = useAuthStore();

  // Role guard — redirect jika bukan Admin.
  if (user && user.role !== "Admin") {
    router.push("/");
    return null;
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900">Pengguna</h1>
        <p className="text-sm text-neutral-500 mt-1">Kelola peran pengguna portal</p>
      </div>
      <UserRoleManager />
    </div>
  );
}
