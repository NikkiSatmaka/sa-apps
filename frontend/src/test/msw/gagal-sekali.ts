import { http, HttpResponse } from "msw";
import { errorEnvelope, successEnvelope } from "../fixtures/envelope";
import { api } from "./base";

/**
 * Handler GET yang gagal (500) pada panggilan pertama lalu berhasil mengembalikan `data`.
 * Dipakai test "tampilkan error lalu coba lagi" (#82): bukti galat tampil dan tombol coba lagi
 * benar-benar meminta ulang ke server.
 */
export function gagalLaluBerhasil(path: string, data: unknown) {
  let panggilan = 0;
  return http.get(api(path), () =>
    ++panggilan === 1
      ? HttpResponse.json(errorEnvelope("Server error"), { status: 500 })
      : HttpResponse.json(successEnvelope(data)),
  );
}

/** Handler GET yang selalu gagal (500). */
export function selaluGagal(path: string) {
  return http.get(api(path), () => HttpResponse.json(errorEnvelope("Server error"), { status: 500 }));
}
