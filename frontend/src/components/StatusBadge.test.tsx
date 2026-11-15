import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["Intake", "bg-neutral-100"],
    ["Awaiting Assignment", "bg-yellow-100"],
    ["Assigned", "bg-blue-100"],
    ["In Progress", "bg-indigo-100"],
    ["Submitted", "bg-green-100"],
    ["Won", "bg-emerald-100"],
    ["Handed Over", "bg-teal-100"],
    ["Closed", "bg-slate-200"],
    ["Lost", "bg-red-100"],
    ["On Hold", "bg-amber-100"],
    ["Status Lain", "bg-neutral-100"],
  ])("status %s berwarna %s", (status, kelas) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(status).className).toContain(kelas);
  });

  it.each([
    ["Scoring", "Sedang Dinilai", "bg-purple-100"],
    ["Need Clarification", "Perlu Klarifikasi Tambahan", "bg-orange-100"],
    ["Manual Review", "Perlu Ditinjau Manual", "bg-pink-100"],
    ["Qualified", "Lolos Kualifikasi", "bg-green-100"],
  ])("Intake menampilkan label %s sebagai %s dengan warna %s", (state, label, kelas) => {
    render(<StatusBadge status="Intake" qualificationState={state} />);
    expect(screen.getByText("Intake")).toBeInTheDocument();
    const badge = screen.getByTitle("Kualifikasi: " + label);
    expect(badge).toHaveTextContent(label);
    expect(badge.className).toContain(kelas);
    expect(badge).toHaveAttribute("title", "Kualifikasi: " + label);
    expect(screen.queryByText(state)).not.toBeInTheDocument();
  });

  it("Intake tanpa qualification_state hanya menampilkan status", () => {
    const { container } = render(<StatusBadge status="Intake" qualificationState={null} />);
    expect(container.querySelectorAll("span")).toHaveLength(1);
  });

  it.each(["Awaiting Assignment", "Assigned", "Won", "Closed", "Lost", "On Hold"])(
    "%s tidak menampilkan qualification_state yang tersisa (hanya bermakna saat Intake)",
    (status) => {
      render(<StatusBadge status={status} qualificationState="Qualified" />);
      expect(screen.queryByText("Qualified")).not.toBeInTheDocument();
    },
  );
});
