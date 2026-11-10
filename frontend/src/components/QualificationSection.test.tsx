import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  http,
  HttpResponse,
  api,
  errorEnvelope,
  renderWithProviders,
  server,
  successEnvelope,
} from "@/test";
import { makeAnswers, makeOpportunitySchema, makeQualificationView } from "@/test/fixtures/opportunity";
import { QualificationSection } from "./QualificationSection";

function useSchema() {
  server.use(http.get(api("/qualification/schema"), () => HttpResponse.json(successEnvelope(makeOpportunitySchema()))));
}

describe("QualificationSection", () => {
  it("tidak merender apa pun tanpa data kualifikasi", () => {
    const { container } = renderWithProviders(<QualificationSection qualification={undefined} targetSubmit={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  describe("proyek baru", () => {
    it("menampilkan status memuat lalu jawaban dari skema, termasuk format rupiah, tanggal, dan header", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({ answers: makeAnswers({ timeline_date: "2026-03-05" }) })}
          targetSubmit="2025-12-31"
        />,
      );
      expect(screen.getByText("Memuat kuesioner...")).toBeInTheDocument();
      expect(await screen.findByRole("heading", { name: "Kuesioner Kualifikasi" })).toBeInTheDocument();
      expect(screen.getByText("Budget MRR").nextElementSibling).toHaveTextContent("Rp 50");
      expect(screen.getByText("Go-live").nextElementSibling).toHaveTextContent("2026");
      expect(screen.getByText("Target submit").nextElementSibling).toHaveTextContent("2025");
      expect(screen.getByText("Nama PIC").nextElementSibling).toHaveTextContent("Budi");
      // jawaban kosong → tanda strip
      expect(screen.getByText("Catatan").nextElementSibling).toHaveTextContent("—");
    });

    it("menampilkan tanggal mentah bila tidak valid dan strip bila header kosong", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({ answers: makeAnswers({ timeline_date: "bukan-tanggal" }) })}
          targetSubmit={null}
        />,
      );
      await screen.findByRole("heading", { name: "Kuesioner Kualifikasi" });
      expect(screen.getByText("Go-live").nextElementSibling).toHaveTextContent("bukan-tanggal");
      expect(screen.getByText("Target submit").nextElementSibling).toHaveTextContent("—");
    });

    it("menampilkan sub-skor dan feedback bila skor tersedia", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({
            sub_scores: { budget: 20, authority: 15, need: 10, timeline: 5 },
            feedback: "Perjelas timeline",
          })}
          targetSubmit={null}
        />,
      );
      await screen.findByText("Sub-skor BANT");
      expect(screen.getByText("20/25")).toBeInTheDocument();
      expect(screen.getByRole("note")).toHaveTextContent("Perjelas timeline");
    });

    it("menampilkan sub-skor tanpa kotak feedback bila feedback kosong", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({ sub_scores: { budget: 25, authority: 25, need: 25, timeline: 25 } })}
          targetSubmit={null}
        />,
      );
      await screen.findByText("Sub-skor BANT");
      expect(screen.queryByRole("note")).not.toBeInTheDocument();
    });

    it("Scoring Pending: menampilkan pesan analisis berjalan dan menyembunyikan skor", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({
            scoring_pending: true,
            sub_scores: { budget: 20, authority: 15, need: 10, timeline: 5 },
          })}
          targetSubmit={null}
        />,
      );
      expect(await screen.findByRole("status")).toHaveTextContent("Analisis AI sedang berjalan");
      expect(screen.queryByText("Sub-skor BANT")).not.toBeInTheDocument();
    });

    it("tanpa skor dan tidak pending: tidak ada blok sub-skor", async () => {
      useSchema();
      renderWithProviders(<QualificationSection qualification={makeQualificationView()} targetSubmit={null} />);
      await screen.findByRole("heading", { name: "Kuesioner Kualifikasi" });
      expect(screen.queryByText("Sub-skor BANT")).not.toBeInTheDocument();
    });

    it("menampilkan pesan gagal bila skema tidak dapat dimuat", async () => {
      server.use(
        http.get(api("/qualification/schema"), () =>
          HttpResponse.json(errorEnvelope("gagal"), { status: 500 }),
        ),
      );
      renderWithProviders(<QualificationSection qualification={makeQualificationView()} targetSubmit={null} />);
      expect(await screen.findByText("Gagal memuat skema kuesioner.")).toBeInTheDocument();
    });

    it("memakai format rupiah dengan nilai berupa string/kosong secara aman", async () => {
      useSchema();
      renderWithProviders(
        <QualificationSection qualification={makeQualificationView({ answers: makeAnswers({ budget_mrr: "" }) })} targetSubmit={null} />,
      );
      await screen.findByRole("heading", { name: "Kuesioner Kualifikasi" });
      expect(screen.getByText("Budget MRR").nextElementSibling).toHaveTextContent("—");
    });
  });

  describe("proyek legacy", () => {
    const legacy = makeQualificationView({
      legacy: true,
      answers: null,
      legacy_data: {
        budget_mrr: 25000000,
        pic_name: "Siti",
        pic_position: "CTO",
        pic_email: "siti@contoh.co.id",
        need_description: "Kebutuhan lama",
        timeline_target: "2025-10-01",
      },
    });

    it("menampilkan metadata BANT lama apa adanya dengan label Legacy", () => {
      renderWithProviders(<QualificationSection qualification={legacy} targetSubmit="2025-12-31" />);
      expect(screen.getByRole("heading", { name: "Detail BANT" })).toBeInTheDocument();
      expect(screen.getByText("Legacy")).toBeInTheDocument();
      expect(screen.getByText("Siti")).toBeInTheDocument();
      expect(screen.getByText(/CTO — siti@contoh.co.id/)).toBeInTheDocument();
      expect(screen.getByText("Kebutuhan lama")).toBeInTheDocument();
      expect(screen.getByText(/Rp 25/)).toBeInTheDocument();
      expect(screen.getByText(/Oktober 2025/)).toBeInTheDocument();
    });

    it("memakai target submit proyek bila timeline lama kosong, dan strip bila keduanya kosong", () => {
      const tanpaTimeline = makeQualificationView({
        legacy: true,
        answers: null,
        legacy_data: { budget_mrr: null, pic_name: null, need_description: null, timeline_target: null },
      });
      const { rerender } = renderWithProviders(<QualificationSection qualification={tanpaTimeline} targetSubmit="2025-12-31" />);
      expect(screen.getByText(/Desember 2025/)).toBeInTheDocument();
      rerender(<QualificationSection qualification={tanpaTimeline} targetSubmit={null} />);
      expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    });

    it("tanpa data lama, skor, atau pending: tidak merender apa pun", () => {
      const { container } = renderWithProviders(
        <QualificationSection qualification={makeQualificationView({ legacy: true, answers: null })} targetSubmit={null} />,
      );
      expect(container).toBeEmptyDOMElement();
    });

    it("Scoring Pending pada proyek tanpa data lama tetap menampilkan status analisis", () => {
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({ legacy: true, answers: null, scoring_pending: true })}
          targetSubmit={null}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent("Analisis AI sedang berjalan");
    });

    it("menampilkan sub-skor proyek lama tanpa data lama", () => {
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({
            legacy: true,
            answers: null,
            sub_scores: { budget: 1, authority: 2, need: 3, timeline: 4 },
          })}
          targetSubmit={null}
        />,
      );
      expect(screen.getByText("4/25")).toBeInTheDocument();
    });

    it("proyek baru tanpa jawaban (answers null) diperlakukan seperti legacy", () => {
      renderWithProviders(
        <QualificationSection
          qualification={makeQualificationView({ legacy: false, answers: null, legacy_data: { need_description: "x" } })}
          targetSubmit={null}
        />,
      );
      expect(screen.getByRole("heading", { name: "Detail BANT" })).toBeInTheDocument();
    });
  });
});
