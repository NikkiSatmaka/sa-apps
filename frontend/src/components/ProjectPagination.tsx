interface ProjectPaginationProps {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function ProjectPagination({
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
}: ProjectPaginationProps) {
  if (totalPages <= 1) return null;

  const firstItem = (page - 1) * pageSize + 1;
  const lastItem = Math.min(page * pageSize, total);

  return (
    <nav
      aria-label="Navigasi halaman proyek"
      className="flex flex-wrap items-center justify-between gap-3"
    >
      <p className="text-sm text-neutral-600">
        Menampilkan {firstItem}–{lastItem} dari {total} proyek
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Halaman sebelumnya"
          className="rounded border border-neutral-300 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          Sebelumnya
        </button>
        <span aria-live="polite" className="text-sm text-neutral-600">
          Halaman {page} dari {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Halaman berikutnya"
          className="rounded border border-neutral-300 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          Berikutnya
        </button>
      </div>
    </nav>
  );
}
