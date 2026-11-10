import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProjectCard, type ProjectCardProps } from "./ProjectCard";

function setup(props: Partial<ProjectCardProps> = {}) {
  const onClick = vi.fn();
  render(
    <ProjectCard
      id="p1"
      projectName="Migrasi Cloud"
      customerName="PT ACME"
      status="Assigned"
      dqNumber="DQ-001"
      lastUpdated="2025-01-02T12:00:00Z"
      onClick={onClick}
      {...props}
    />,
  );
  return { onClick, card: screen.getByRole("button", { name: "Proyek Migrasi Cloud - PT ACME" }) };
}

describe("ProjectCard", () => {
  it("menampilkan nama, customer, status, tanggal, dan DQ Number", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Migrasi Cloud" })).toBeInTheDocument();
    expect(screen.getByText("PT ACME")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
    expect(screen.getByText(/Update: 2 Jan 2025/)).toBeInTheDocument();
    expect(screen.getByText("DQ-001")).toBeInTheDocument();
    expect(screen.queryByText("Menunggu DQ")).not.toBeInTheDocument();
  });

  it("menampilkan badge Menunggu DQ dan tanpa blok DQ bila dq_number null", () => {
    setup({ dqNumber: null });
    expect(screen.getByText("Menunggu DQ")).toBeInTheDocument();
    expect(screen.queryByText(/^DQ:/)).not.toBeInTheDocument();
  });

  it.each([
    ["New", "bg-neutral-100"],
    ["Pending Assignment", "bg-yellow-100"],
    ["Assigned", "bg-blue-100"],
    ["Ready", "bg-green-100"],
    ["Closed-Win", "bg-emerald-100"],
    ["Lost", "bg-red-100"],
    ["Need Clarification", "bg-orange-100"],
    ["Status Lain", "bg-neutral-100"],
  ])("status %s berwarna %s", (status, kelas) => {
    setup({ status });
    expect(screen.getByText(status).className).toContain(kelas);
  });

  it("SLA badge tampil hanya bila DQ belum diinput dan slaDaysElapsed ada", () => {
    setup({ dqNumber: null, slaDaysElapsed: 3, slaIsLocked: true });
    expect(screen.getByLabelText("SLA countdown: H+3 hari, folder terkunci")).toBeInTheDocument();
  });

  it("SLA badge tidak tampil bila DQ sudah ada atau slaDaysElapsed kosong", () => {
    const { card } = setup({ slaDaysElapsed: 3 });
    expect(card).toBeInTheDocument();
    expect(screen.queryByLabelText(/SLA countdown/)).not.toBeInTheDocument();
  });

  it("SLA badge tidak tampil tanpa slaDaysElapsed meski DQ null", () => {
    setup({ dqNumber: null, slaDaysElapsed: null });
    expect(screen.queryByLabelText(/SLA countdown/)).not.toBeInTheDocument();
  });

  it("menampilkan BANT Passed / not passed menurut ambang 60, dan tidak bila tanpa skor", () => {
    const { unmount } = render(
      <ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="2025-01-01" bantScore={60} />,
    );
    expect(screen.getByText("BANT Passed")).toBeInTheDocument();
    unmount();
    const r2 = render(
      <ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="2025-01-01" bantScore={59} />,
    );
    expect(screen.getByText("BANT not passed")).toBeInTheDocument();
    r2.unmount();
    render(<ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="2025-01-01" bantScore={null} />);
    expect(screen.queryByText(/BANT/)).not.toBeInTheDocument();
  });

  it("klik memanggil onClick", async () => {
    const { onClick, card } = setup();
    await userEvent.click(card);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Enter dan Spasi memicu onClick; tombol lain tidak", async () => {
    const { onClick, card } = setup();
    card.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onClick).toHaveBeenCalledTimes(2);
    await userEvent.keyboard("a");
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("tidak error saat onClick tidak diberikan", async () => {
    render(<ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="2025-01-01" />);
    const card = screen.getByRole("button");
    card.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.click(card);
  });

  it("tanggal kosong atau tak valid tidak tampil sebagai 'Invalid Date'", () => {
    const { unmount } = render(
      <ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="" />,
    );
    expect(screen.getByText("Update:")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
    unmount();
    render(<ProjectCard id="a" projectName="A" customerName="C" status="New" dqNumber="x" lastUpdated="bukan-tanggal" />);
    expect(screen.getByText("Update: bukan-tanggal")).toBeInTheDocument();
  });
});
