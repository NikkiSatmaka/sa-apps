/** Envelope respons backend (`success_response`/`error_response` di backend/app/schemas/response.py). */
export function successEnvelope<T>(data: T, message = "Success") {
  return { status: "success" as const, data, message };
}

export function errorEnvelope<T = null>(message: string, data: T | null = null) {
  return { status: "error" as const, data, message };
}
