import { NextResponse } from "next/server";

/**
 * Health endpoint untuk HEALTHCHECK Docker.
 *
 * Sengaja TIDAK memanggil backend: frontend dianggap sehat selama proses
 * Next.js melayani request. Bila backend turun, itu bukan salah container
 * frontend, jadi tidak boleh membuatnya ikut "unhealthy".
 */
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
