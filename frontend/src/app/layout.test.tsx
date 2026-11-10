import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import RootLayout, { metadata, viewport } from "./layout";

describe("root layout", () => {
  const html = renderToStaticMarkup(
    <RootLayout>
      <p>Isi aplikasi</p>
    </RootLayout>,
  );

  it("membuat shell <html lang=id> yang membungkus konten", () => {
    expect(html).toMatch(/^<html lang="id">/);
    expect(html).toContain("<p>Isi aplikasi</p>");
  });

  it("memasang ikon dan preconnect font di <head>", () => {
    expect(html).toContain('rel="icon" href="/icons/icon-192x192.png"');
    expect(html).toContain('rel="preconnect" href="https://fonts.googleapis.com"');
  });

  it("metadata PWA & viewport responsif terdefinisi", () => {
    expect(metadata.manifest).toBe("/manifest.json");
    expect(metadata.title).toMatch(/Portal SA/);
    expect(viewport).toMatchObject({ width: "device-width", initialScale: 1 });
  });
});
