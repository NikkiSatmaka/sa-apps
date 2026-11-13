"use client";

/**
 * Pesan error pemuatan data + tombol "Coba lagi" (#82).
 *
 * Dipakai di semua tempat yang memuat data lewat SWR: kegagalan request harus tampil sebagai
 * error yang jelas dan bisa dicoba ulang, bukan jatuh diam-diam ke keadaan kosong ("Belum ada ...")
 * yang menyesatkan. `onRetry` biasanya `mutate` dari `useSWR`.
 */
interface LoadErrorProps {
  /** Pesan untuk user, mis. "Gagal memuat daftar proyek." */
  message: string;
  /** Dipanggil saat user menekan "Coba lagi"; boleh mengembalikan promise. */
  onRetry: () => unknown;
  className?: string;
}

export function LoadError({ message, onRetry, className = "" }: LoadErrorProps) {
  const handleRetry = () => {
    // `mutate` SWR menolak promise bila request ulang gagal lagi; error itu sudah tercermin di
    // state `error` SWR (pesan tetap tampil), jadi jangan jadi unhandled rejection.
    Promise.resolve(onRetry()).catch(() => {});
  };

  return (
    <div
      role="alert"
      className={`flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 ${className}`}
    >
      <p className="text-sm text-red-700">{message}</p>
      <button
        type="button"
        onClick={handleRetry}
        className="shrink-0 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm font-medium
                   text-red-700 transition-colors hover:bg-red-100 min-h-[44px]"
      >
        Coba lagi
      </button>
    </div>
  );
}
