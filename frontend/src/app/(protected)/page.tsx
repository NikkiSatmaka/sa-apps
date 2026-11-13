"use client";

import { useAuthStore } from "@/store/auth";
import SalesDashboard from "./dashboard/sales/page";
import SADashboard from "./dashboard/sa/page";
import LeadSADashboard from "./dashboard/lead-sa/page";

/**
 * Halaman utama (/) — render dashboard sesuai role
 *
 * Setiap role punya dashboard fungsional sendiri:
 * - Sales dan Product: listing proyek miliknya (dashboard requester)
 * - SA: listing proyek assigned + activity
 * - Lead_SA: overview + utilisasi SA + effort per proyek
 *
 * Admin bukan role melainkan flag `is_admin` (ADR 0012): beranda mengikuti role fungsional;
 * dashboard Lead SA tetap terjangkau lewat menu samping untuk admin.
 */

function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-8 bg-neutral-200 rounded w-1/3" />
      <div className="h-4 bg-neutral-100 rounded w-1/2" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-neutral-100 rounded-lg" />
        ))}
      </div>
      <div className="h-48 bg-neutral-100 rounded-lg" />
    </div>
  );
}

export default function HomePage() {
  const { user, isLoading } = useAuthStore();

  if (isLoading || !user) {
    return <DashboardSkeleton />;
  }

  switch (user.role) {
    case "Sales":
    case "Product":
      return <SalesDashboard />;
    case "SA":
      return <SADashboard />;
    case "Lead_SA":
      return <LeadSADashboard />;
    default:
      return <SADashboard />;
  }
}
