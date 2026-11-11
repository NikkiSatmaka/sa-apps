// Ringkasan cakupan frontend untuk CI (tiket #71). Membaca coverage/coverage-summary.json
// (reporter json-summary) lalu mencetak tabel markdown + peringatan per berkas.
//
// TIDAK memblok: gerbang yang memblok adalah `coverage.thresholds` di vitest.config.mts
// (global: baris >= 90%, cabang >= 80%). Berkas individual di bawah ambang hanya
// diperingatkan (::warning), selaras gerbang backend (CONSTRAINTS.md bagian 1).
//
// Pemakaian: node scripts/cakupan-ringkasan.mjs [coverage/coverage-summary.json]
import { readFileSync } from "node:fs";
import { relative } from "node:path";

const AMBANG_BARIS = 90;
const AMBANG_CABANG = 80;

const berkas = process.argv[2] ?? "coverage/coverage-summary.json";
let data;
try {
  data = JSON.parse(readFileSync(berkas, "utf8"));
} catch (err) {
  console.log(`Ringkasan cakupan tidak tersedia (${berkas}): ${err.message}`);
  process.exit(0); // jangan menutupi kegagalan test dengan kegagalan skrip ini
}

// Tanpa statement/cabang (mis. barrel re-export) tidak ada yang bisa gagal -> 100%.
const persen = (x) => (x.total === 0 || x.pct === "Unknown" ? 100 : x.pct);
const total = data.total;
const baris = [];
baris.push("## Cakupan frontend (Vitest, v8)", "");
baris.push(
  `Gerbang memblok (global): baris >= ${AMBANG_BARIS}% dan cabang >= ${AMBANG_CABANG}% (CONSTRAINTS.md).`,
  "",
  `**Total:** baris ${persen(total.lines)}% (${total.lines.covered}/${total.lines.total}), ` +
    `cabang ${persen(total.branches)}% (${total.branches.covered}/${total.branches.total})`,
  "",
);

const lemah = Object.entries(data)
  .filter(([nama]) => nama !== "total")
  .map(([nama, v]) => ({ nama: relative(process.cwd(), nama), v }))
  .filter(({ v }) => persen(v.lines) < AMBANG_BARIS || persen(v.branches) < AMBANG_CABANG)
  .sort((a, b) => persen(a.v.branches) - persen(b.v.branches));

if (lemah.length === 0) {
  baris.push("Semua berkas memenuhi ambang baris/cabang.");
} else {
  baris.push(
    `### Berkas di bawah ambang (${lemah.length}; peringatan, tidak memblok sendirian)`,
    "",
    "| Berkas | Baris | Cabang |",
    "| --- | --- | --- |",
  );
  for (const { nama, v } of lemah) {
    baris.push(`| \`${nama}\` | ${persen(v.lines)}% | ${persen(v.branches)}% |`);
    console.error(
      `::warning title=Berkas di bawah ambang cakupan::${nama}: baris ${persen(v.lines)}%, cabang ${persen(v.branches)}%`,
    );
  }
}
console.log(baris.join("\n"));
