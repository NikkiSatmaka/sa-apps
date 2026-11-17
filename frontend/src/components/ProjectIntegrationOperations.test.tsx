import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse, server, api, successEnvelope } from "@/test";
import { renderWithProviders } from "@/test/render";
import { ProjectIntegrationOperations } from "./ProjectIntegrationOperations";
import type { IntegrationOperationResponse } from "@/lib/api/projects";

const OPERATION_ID = "operation-1";
const PROJECT_ID = "PRJ-203";

function failedEmailOperation(context: Record<string, unknown> = {}): IntegrationOperationResponse {
  return {
    id: OPERATION_ID,
    operation_type: "email_delivery",
    action: "send_assignment_email",
    status: "failed",
    attempts: [{
      attempt: 1,
      status: "failed",
      started_at: "2026-11-17T10:00:00Z",
      finished_at: "2026-11-17T10:00:01Z",
      outcome: "Gmail did not confirm message delivery.",
      actionable_error: "Check recipient status before manually sending.",
    }],
    started_at: "2026-11-17T10:00:00Z",
    finished_at: "2026-11-17T10:00:01Z",
    outcome: "Gmail did not confirm message delivery.",
    actionable_error: "Check recipient status before manually sending.",
    retryable: false,
    context,
  };
}

describe("ProjectIntegrationOperations", () => {
  it("shows history and records manually confirmed recovery without replay", async () => {
    const onRepaired = vi.fn();
    let repairBody: unknown;
    server.use(http.post(
      api(`/projects/${PROJECT_ID}/integration-operations/${OPERATION_ID}/repair`),
      async ({ request }) => {
        repairBody = await request.json();
        return HttpResponse.json(successEnvelope({
          ...failedEmailOperation({
            manual_repair: {
              actor_user_id: "lead-user",
              repaired_at: "2026-11-17T10:05:00Z",
              recipient_checked_not_received: true,
              manually_delivered_outside_app: true,
            },
          }),
        }));
      },
    ));
    const { user } = renderWithProviders(
      <ProjectIntegrationOperations projectId={PROJECT_ID} operations={[failedEmailOperation()]} user={{ role: "Lead_SA" }} onRepaired={onRepaired} />,
    );

    expect(screen.getByRole("heading", { name: "Riwayat operasi integrasi" })).toBeTruthy();
    expect(screen.getByText("Status: failed · perlu ditangani")).toBeTruthy();
    expect(screen.getAllByText(/Gmail did not confirm message delivery/)).toHaveLength(2);
    expect(screen.getAllByText(/Check recipient status before manually sending/)).toHaveLength(2);
    expect(screen.getByText(/Dimulai:/)).toBeTruthy();
    expect(screen.getByText(/Selesai:/)).toBeTruthy();
    expect(screen.getByText(/Percobaan 1: failed/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Rekonsiliasi manual" }));
    expect(screen.getByText(/Portal SA tidak akan mengirim ulang email/)).toBeTruthy();
    const save = screen.getByRole("button", { name: "Catat pemulihan manual" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /memastikan penerima belum menerima/ }));
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /mengirim notifikasi secara manual di luar aplikasi/ }));
    await user.click(save);

    await waitFor(() => expect(onRepaired).toHaveBeenCalledOnce());
    expect(repairBody).toEqual({ recipient_checked_not_received: true, manually_delivered_outside_app: true });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not offer repair to an unauthorized user", () => {
    renderWithProviders(<ProjectIntegrationOperations projectId={PROJECT_ID} operations={[failedEmailOperation()]} user={{ role: "SA" }} onRepaired={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Rekonsiliasi manual" })).toBeNull();
  });

  it("shows operator confirmation without claiming provider confirmation or offering another repair", () => {
    renderWithProviders(<ProjectIntegrationOperations
      projectId={PROJECT_ID}
      operations={[failedEmailOperation({ manual_repair: {
        actor_user_id: "lead-user",
        repaired_at: "2026-11-17T10:05:00Z",
        recipient_checked_not_received: true,
        manually_delivered_outside_app: true,
      } })]}
      user={{ role: "Lead_SA" }}
      onRepaired={vi.fn()}
    />);
    expect(screen.queryByRole("button", { name: "Rekonsiliasi manual" })).toBeNull();
    expect(screen.getByText("Pemulihan manual dikonfirmasi operator")).toBeTruthy();
    expect(screen.getByText(/provider delivery was not confirmed/i)).toBeTruthy();
  });
});
