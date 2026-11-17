"use client";

import { useState } from "react";
import { recordManualEmailRepair, type IntegrationOperationResponse } from "@/lib/api/projects";
import { isPrivileged, type Actor } from "@/lib/roles";

interface Props {
  projectId: string;
  operations: IntegrationOperationResponse[];
  user: Actor | null;
  onRepaired: () => void;
}

type ManualRepair = {
  actor_user_id: string;
  repaired_at: string;
  recipient_checked_not_received: true;
  manually_delivered_outside_app: true;
};

function manualRepair(operation: IntegrationOperationResponse): ManualRepair | null {
  const value = operation.context.manual_repair;
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.actor_user_id !== "string" ||
    typeof record.repaired_at !== "string" ||
    record.recipient_checked_not_received !== true ||
    record.manually_delivered_outside_app !== true
  ) return null;
  return {
    actor_user_id: record.actor_user_id,
    repaired_at: record.repaired_at,
    recipient_checked_not_received: true,
    manually_delivered_outside_app: true,
  };
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Belum tersedia";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("id-ID");
}

export function ProjectIntegrationOperations({ projectId, operations, user, onRepaired }: Props) {
  const [operationId, setOperationId] = useState<string | null>(null);
  const [recipientChecked, setRecipientChecked] = useState(false);
  const [manuallyDelivered, setManuallyDelivered] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const operation = operations.find((item) => item.id === operationId);

  if (operations.length === 0) return null;

  const closeDialog = () => {
    setOperationId(null);
    setRecipientChecked(false);
    setManuallyDelivered(false);
    setError(null);
  };

  const saveRepair = async () => {
    if (!operation || !recipientChecked || !manuallyDelivered || saving) return;
    setSaving(true);
    setError(null);
    try {
      await recordManualEmailRepair(projectId, operation.id);
      closeDialog();
      onRepaired();
    } catch {
      setError("Gagal menyimpan catatan pemulihan. Silakan coba lagi.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <section aria-labelledby="integration-operations-heading" className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 id="integration-operations-heading" className="text-sm font-semibold text-neutral-800">
          Riwayat operasi integrasi
        </h2>
        <ul className="mt-3 space-y-4">
          {operations.map((item) => {
            const repair = manualRepair(item);
            const canRepair = isPrivileged(user) && item.operation_type === "email_delivery" && item.status === "failed" && !repair;
            const label = item.status === "failed"
              ? repair ? "failed · pemulihan manual dicatat operator" : "failed · perlu ditangani"
              : item.status;
            return (
              <li key={item.id} className="border-t border-neutral-100 pt-3 first:border-0 first:pt-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-neutral-800">{item.action}</h3>
                  <span className="text-xs font-medium text-neutral-600">Status: {label}</span>
                </div>
                <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-neutral-600 sm:grid-cols-2">
                  <div><dt className="inline font-medium">Dimulai: </dt><dd className="inline">{formatTimestamp(item.started_at)}</dd></div>
                  <div><dt className="inline font-medium">Selesai: </dt><dd className="inline">{formatTimestamp(item.finished_at)}</dd></div>
                </dl>
                {item.outcome && <p className="mt-2 text-sm text-neutral-700">Hasil: {item.outcome}</p>}
                {item.actionable_error && <p className="mt-2 text-sm text-amber-800">Tindakan: {item.actionable_error}</p>}
                {item.attempts.length > 0 && (
                  <ol className="mt-3 space-y-2 text-xs text-neutral-600" aria-label={`Riwayat percobaan ${item.action}`}>
                    {item.attempts.map((attempt) => (
                      <li key={`${item.id}-${attempt.attempt}-${attempt.started_at}`}>
                        <p>Percobaan {attempt.attempt}: {attempt.status} · mulai {formatTimestamp(attempt.started_at)}{attempt.finished_at && ` · selesai ${formatTimestamp(attempt.finished_at)}`}</p>
                        {attempt.outcome && <p className="mt-1">Hasil: {attempt.outcome}</p>}
                        {attempt.actionable_error && <p className="mt-1 text-amber-800">Tindakan: {attempt.actionable_error}</p>}
                      </li>
                    ))}
                  </ol>
                )}
                {repair && (
                  <div className="mt-3 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-900">
                    <p className="font-medium">Pemulihan manual dikonfirmasi operator</p>
                    <p className="mt-1">Penerima telah diperiksa dan notifikasi dikirim manual di luar aplikasi.</p>
                    <p className="mt-1 text-xs">Dicatat {formatTimestamp(repair.repaired_at)} · operator ID {repair.actor_user_id}; provider delivery was not confirmed.</p>
                  </div>
                )}
                {canRepair && <button type="button" onClick={() => setOperationId(item.id)} className="mt-3 min-h-[40px] rounded-lg border border-primary-600 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-50">Rekonsiliasi manual</button>}
              </li>
            );
          })}
        </ul>
      </section>
      {operation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <section role="dialog" aria-modal="true" aria-labelledby="manual-email-repair-heading" className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
            <h2 id="manual-email-repair-heading" className="text-lg font-semibold text-neutral-900">Konfirmasi pemulihan email manual</h2>
            <p className="mt-3 text-sm text-neutral-700">Portal SA tidak akan mengirim ulang email. Catatan ini hanya merekam konfirmasi operator, bukan konfirmasi pengiriman dari Gmail.</p>
            <div className="mt-4 space-y-3 text-sm text-neutral-700">
              <label className="flex items-start gap-2"><input type="checkbox" checked={recipientChecked} onChange={(event) => setRecipientChecked(event.target.checked)} /><span>Saya sudah memastikan penerima belum menerima email asli.</span></label>
              <label className="flex items-start gap-2"><input type="checkbox" checked={manuallyDelivered} onChange={(event) => setManuallyDelivered(event.target.checked)} /><span>Saya sudah mengirim notifikasi secara manual di luar aplikasi.</span></label>
            </div>
            {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={closeDialog} disabled={saving} className="min-h-[40px] rounded-lg border border-neutral-300 px-3 py-2 text-sm text-neutral-700 disabled:opacity-50">Batal</button>
              <button type="button" onClick={saveRepair} disabled={!recipientChecked || !manuallyDelivered || saving} className="min-h-[40px] rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">{saving ? "Menyimpan..." : "Catat pemulihan manual"}</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
