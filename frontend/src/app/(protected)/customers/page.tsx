"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { useAuthStore } from "@/store/auth";
import { isPrivileged } from "@/lib/roles";
import { createCustomer, renameCustomer, type CustomerOption } from "@/lib/api/projects";
import { fetcher } from "@/lib/fetcher";

export default function CustomersPage() {
  const user = useAuthStore((state) => state.user);
  const authorized = isPrivileged(user);
  const { data: customers = [], error, isLoading, mutate } = useSWR<CustomerOption[]>(authorized ? "/customers" : null, fetcher);
  const [search, setSearch] = useState("");
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  const visibleCustomers = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return customers.filter((customer) => customer.name.toLocaleLowerCase().includes(query));
  }, [customers, search]);

  if (!authorized) return <p role="alert">Anda tidak memiliki akses mengelola Customer.</p>;

  async function create() {
    setSaving(true);
    setMessage("");
    try {
      await createCustomer(newName);
      setNewName("");
      await mutate();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Gagal membuat Customer.");
    } finally {
      setSaving(false);
    }
  }

  async function rename(id: string) {
    setSaving(true);
    setMessage("");
    try {
      await renameCustomer(id, editingName);
      setEditingId(null);
      setEditingName("");
      await mutate();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Gagal mengganti nama Customer.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="max-w-3xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-neutral-900">Customer</h1>
        <p className="mt-1 text-sm text-neutral-500">Kelola identitas Customer yang digunakan oleh Proyek.</p>
      </header>
      <label className="block space-y-1">
        <span className="text-sm font-medium">Cari Customer</span>
        <input aria-label="Cari Customer" value={search} onChange={(event) => setSearch(event.target.value)} className="w-full rounded border p-2" />
      </label>
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void create(); }}>
        <input aria-label="Nama Customer baru" value={newName} onChange={(event) => setNewName(event.target.value)} required maxLength={150} className="min-w-0 flex-1 rounded border p-2" />
        <button type="submit" disabled={saving} className="rounded bg-primary-600 px-4 py-2 text-white">Buat Customer</button>
      </form>
      {message && <p role="alert">{message}</p>}
      {error && <p role="alert">Gagal memuat Customer.</p>}
      {isLoading ? <p>Memuat Customer…</p> : (
        <ul className="divide-y rounded border">
          {visibleCustomers.map((customer) => (
            <li key={customer.id} className="flex items-center gap-2 p-3">
              {editingId === customer.id ? <>
                <input aria-label={`Nama Customer ${customer.name}`} value={editingName} onChange={(event) => setEditingName(event.target.value)} required maxLength={150} className="min-w-0 flex-1 rounded border p-2" />
                <button type="button" disabled={saving} onClick={() => void rename(customer.id)} className="rounded border px-3 py-2">Simpan</button>
                <button type="button" onClick={() => setEditingId(null)} className="rounded border px-3 py-2">Batal</button>
              </> : <>
                <span className="flex-1">{customer.name}</span>
                <button type="button" onClick={() => { setEditingId(customer.id); setEditingName(customer.name); }} className="rounded border px-3 py-2">Ganti nama</button>
              </>}
            </li>
          ))}
          {!isLoading && visibleCustomers.length === 0 && <li className="p-3 text-sm text-neutral-500">Tidak ada Customer.</li>}
        </ul>
      )}
    </section>
  );
}
