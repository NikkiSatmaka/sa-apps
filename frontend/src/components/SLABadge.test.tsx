import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SLABadge } from "./SLABadge";

describe("SLABadge", () => {
  it.each([
    [0, "bg-green-100"],
    [2, "bg-green-100"],
    [3, "bg-yellow-100"],
    [4, "bg-yellow-100"],
    [5, "bg-red-100"],
    [9, "bg-red-100"],
  ])("H+%i berwarna sesuai ambang (%s)", (days, kelas) => {
    render(<SLABadge daysElapsed={days} isLocked={false} />);
    const badge = screen.getByLabelText(`SLA countdown: H+${days} hari`);
    expect(badge).toHaveTextContent(`H+${days}`);
    expect(badge.className).toContain(kelas);
  });

  it("menandai folder terkunci di label dan title", () => {
    render(<SLABadge daysElapsed={6} isLocked />);
    const badge = screen.getByLabelText("SLA countdown: H+6 hari, folder terkunci");
    expect(badge).toHaveAttribute("title", "SLA DQ Number: H+6 hari (folder terkunci)");
  });

  it("tidak menyebut terkunci bila folder tidak terkunci", () => {
    render(<SLABadge daysElapsed={1} isLocked={false} />);
    expect(screen.getByLabelText(/SLA countdown/)).not.toHaveAttribute("title", expect.stringContaining("terkunci"));
  });
});

describe("SLABadge — timer dijeda (On Hold)", () => {
  it("menandai dijeda di teks, label, dan title", () => {
    render(<SLABadge daysElapsed={3} isLocked={false} isPaused />);
    const badge = screen.getByLabelText("SLA countdown: H+3 hari, timer dijeda");
    expect(badge).toHaveTextContent("H+3");
    expect(badge).toHaveTextContent("Dijeda");
    expect(badge).toHaveAttribute("title", "SLA DQ Number: H+3 hari (timer dijeda)");
  });

  it("tanpa isPaused tidak menampilkan Dijeda", () => {
    render(<SLABadge daysElapsed={3} isLocked={false} />);
    expect(screen.getByLabelText("SLA countdown: H+3 hari")).not.toHaveTextContent("Dijeda");
  });
});

