"use client";

import { useAuthStore } from "@/store/auth";
import { logout } from "@/lib/auth";
import { labelPeran } from "@/lib/roles";

/**
 * Halaman Profil (/profile) — read-only.
 *
 * Login memakai Google Account (OAuth), jadi nama, email, dan avatar dikelola
 * di akun Google. Tidak ada password di Portal SA, sehingga tidak ada form ganti password.
 */
export default function ProfilePage() {
  const { user, isLoading, clearUser } = useAuthStore();

  if (isLoading || !user) {
    return <div className="h-48 max-w-2xl bg-neutral-100 rounded-lg animate-pulse" />;
  }

  const rows: { label: string; value: string }[] = [
    { label: "Nama", value: user.full_name },
    { label: "Email", value: user.email },
    { label: "Role", value: labelPeran(user) },
  ];

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold text-neutral-900">Profil Saya</h1>

      <section className="bg-white border border-neutral-200 rounded-lg p-6 space-y-6">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary-500 flex items-center justify-center">
            <span className="text-2xl font-medium text-white">
              {user.full_name.charAt(0).toUpperCase()}
            </span>
          </div>
          <div>
            <p className="text-lg font-medium text-neutral-900">{user.full_name}</p>
            <p className="text-sm text-neutral-500">{labelPeran(user)}</p>
          </div>
        </div>

        <dl className="divide-y divide-neutral-100">
          {rows.map((row) => (
            <div key={row.label} className="py-3 grid grid-cols-3 gap-4">
              <dt className="text-sm text-neutral-500">{row.label}</dt>
              <dd className="col-span-2 text-sm text-neutral-900 break-all">{row.value}</dd>
            </div>
          ))}
        </dl>

        <p className="text-sm text-neutral-500 bg-neutral-50 rounded-lg p-3">
          Akun ini masuk melalui Google. Untuk mengubah nama, foto, atau password,
          kelola langsung di akun Google Anda. Role diatur oleh Admin.
        </p>
      </section>

      <button
        type="button"
        onClick={() => {
          clearUser();
          void logout();
        }}
        className="min-h-[44px] px-4 rounded-lg border border-neutral-300 text-sm font-medium
                   text-neutral-700 hover:bg-red-50 hover:text-red-600 hover:border-red-200"
      >
        Keluar
      </button>
    </div>
  );
}
