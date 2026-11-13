/**
 * Offline Queue — Menyimpan submission saat offline, sync otomatis saat online
 * (Requirement 12.5)
 *
 * Menggunakan localStorage sebagai storage sederhana untuk MVP.
 * Saat koneksi terputus, submission disimpan di queue.
 * Saat koneksi kembali, queue di-sync ke server secara otomatis.
 *
 * Indikator visual "Menunggu Sinkronisasi" ditampilkan untuk entry yang belum tersinkron.
 */

const QUEUE_STORAGE_KEY = "portal-sa-offline-queue";

/** Batas percobaan ulang untuk respons sementara dari server (5xx/408/429) sebelum item ditandai gagal. */
const MAX_SERVER_RETRIES = 5;

export interface QueuedSubmission {
  id: string;
  url: string;
  method: "POST" | "PUT" | "PATCH";
  body: string;
  headers: Record<string, string>;
  createdAt: number;
  retryCount: number;
  description: string; // Deskripsi singkat untuk UI (misal: "Activity Log: Meeting Pre-Sales")
  /**
   * Alasan gagal permanen. Bila terisi, item TIDAK dikirim ulang tetapi tetap disimpan agar data
   * tidak hilang diam-diam; pengguna melihatnya di indikator dan memutuskan membuangnya.
   */
  failure?: string;
}

export interface OfflineQueueState {
  items: QueuedSubmission[];
  isSyncing: boolean;
}

/** Ambil semua item dari queue */
export function getQueuedItems(): QueuedSubmission[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(QUEUE_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/** Item yang masih menunggu dikirim (belum ditandai gagal permanen) */
export function getPendingItems(): QueuedSubmission[] {
  return getQueuedItems().filter((item) => !item.failure);
}

/** Item yang ditandai gagal permanen (4xx, atau 5xx melewati batas percobaan) */
export function getFailedItems(): QueuedSubmission[] {
  return getQueuedItems().filter((item) => item.failure);
}

/** Simpan queue ke localStorage */
function saveQueue(items: QueuedSubmission[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(items));
}

/** Tambah submission ke offline queue */
export function enqueueSubmission(
  url: string,
  method: "POST" | "PUT" | "PATCH",
  body: unknown,
  headers: Record<string, string> = {},
  description = "Submission"
): QueuedSubmission {
  const item: QueuedSubmission = {
    id: `oq-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    url,
    method,
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...headers },
    createdAt: Date.now(),
    retryCount: 0,
    description,
  };

  const items = getQueuedItems();
  items.push(item);
  saveQueue(items);

  // Dispatch custom event agar komponen UI bisa react
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated"));
  }

  return item;
}

/** Hapus item dari queue (setelah berhasil di-sync) */
export function dequeueSubmission(id: string): void {
  const items = getQueuedItems().filter((item) => item.id !== id);
  saveQueue(items);

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated"));
  }
}

/** Increment retry count untuk item tertentu */
function incrementRetry(id: string): void {
  const items = getQueuedItems().map((item) =>
    item.id === id ? { ...item, retryCount: item.retryCount + 1 } : item
  );
  saveQueue(items);
}

/** Tandai item gagal permanen dengan alasan; item tetap di antrean */
function markFailed(id: string, reason: string): void {
  const items = getQueuedItems().map((item) =>
    item.id === id ? { ...item, failure: reason } : item
  );
  saveQueue(items);
}

/** Buang semua item gagal permanen (aksi eksplisit pengguna) */
export function discardFailedItems(): void {
  saveQueue(getPendingItems());

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated"));
  }
}

/** Respons yang layak dicoba lagi: server error, request timeout, atau rate limit */
function isTransientStatus(status: number): boolean {
  return status >= 500 || status === 408 || status === 429;
}

/** Cek apakah device sedang online */
export function isOnline(): boolean {
  if (typeof navigator === "undefined") return true;
  return navigator.onLine;
}

/** Sync semua queued submissions ke server */
export async function syncOfflineQueue(): Promise<{
  synced: number;
  failed: number;
}> {
  if (!isOnline()) {
    return { synced: 0, failed: 0 };
  }

  // Item gagal permanen dilewati: tidak dikirim ulang dan tidak dihitung lagi.
  const items = getPendingItems();
  if (items.length === 0) {
    return { synced: 0, failed: 0 };
  }

  let synced = 0;
  let failed = 0;

  for (const item of items) {
    try {
      const response = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body,
      });

      if (response.ok) {
        // Hanya yang benar-benar berhasil yang dibuang dari queue
        dequeueSubmission(item.id);
        synced++;
      } else if (isTransientStatus(response.status)) {
        // Server error / timeout / rate limit — retry nanti, dengan batas percobaan
        incrementRetry(item.id);
        if (item.retryCount + 1 >= MAX_SERVER_RETRIES) {
          markFailed(
            item.id,
            `Server menolak setelah ${MAX_SERVER_RETRIES} percobaan (HTTP ${response.status})`
          );
        }
        failed++;
      } else {
        // Error klien (401/403/409/422, ...): mengirim ulang tidak akan membantu, tetapi data
        // jangan hilang diam-diam — simpan dengan alasan agar pengguna bisa memutuskan.
        markFailed(item.id, `Ditolak server (HTTP ${response.status})`);
        failed++;
      }
    } catch {
      // Network error — tetap di queue
      incrementRetry(item.id);
      failed++;
    }
  }

  // Notify UI
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated"));
  }

  return { synced, failed };
}

/**
 * Inisialisasi offline queue listeners.
 * Panggil sekali saat app mount (di layout atau provider).
 */
export function initOfflineSync(): () => void {
  if (typeof window === "undefined") return () => {};

  // Sync saat koneksi kembali
  const handleOnline = () => {
    syncOfflineQueue();
  };

  // Register Background Sync jika tersedia
  const registerBackgroundSync = async () => {
    if ("serviceWorker" in navigator && "SyncManager" in window) {
      try {
        const registration = await navigator.serviceWorker.ready;
        await (registration as any).sync.register("sync-offline-submissions");
      } catch {
        // Background Sync tidak tersedia — fallback ke online event
      }
    }
  };

  window.addEventListener("online", handleOnline);
  registerBackgroundSync();

  // Coba sync jika ada item yang tertunda saat init
  if (isOnline() && getQueuedItems().length > 0) {
    syncOfflineQueue();
  }

  // Return cleanup function
  return () => {
    window.removeEventListener("online", handleOnline);
  };
}

/**
 * Helper: Fetch wrapper yang otomatis queue saat offline
 *
 * Gunakan ini sebagai pengganti fetch biasa untuk form submission.
 * Jika offline, otomatis masuk queue dan tampilkan indikator "Menunggu Sinkronisasi".
 */
export async function submitWithOfflineSupport(
  url: string,
  method: "POST" | "PUT" | "PATCH",
  body: unknown,
  options: {
    headers?: Record<string, string>;
    description?: string;
  } = {}
): Promise<{ queued: boolean; response?: Response }> {
  const { headers = {}, description = "Submission" } = options;

  // Jika offline, langsung queue
  if (!isOnline()) {
    enqueueSubmission(url, method, body, headers, description);
    return { queued: true };
  }

  // Jika online, coba kirim langsung
  try {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
    return { queued: false, response };
  } catch {
    // Gagal (kemungkinan koneksi putus di tengah jalan) — queue
    enqueueSubmission(url, method, body, headers, description);
    return { queued: true };
  }
}
