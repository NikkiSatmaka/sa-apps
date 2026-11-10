/** URL absolut API untuk handler MSW (sama dengan NEXT_PUBLIC_API_URL di vitest.config). */
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost/api/v1";
export const api = (path: string) => `${API}${path}`;
