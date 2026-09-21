import { api, type Approval } from "@/lib/api";
import type { InboxEntry } from "@/lib/approvals";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { KillSwitchControl } from "@/components/kill-switch-control";
import { ApprovalsInbox } from "./approvals-inbox";

async function toEntry(approval: Approval): Promise<InboxEntry> {
  try {
    const decision = await api.getDecision(approval.decision_id);
    const project = await api.getProject(decision.project_id).catch(() => null);
    return { kind: "approval", id: `approval-${approval.id}`, approval, decision, project };
  } catch {
    return { kind: "approval", id: `approval-${approval.id}`, approval, decision: null, project: null };
  }
}

export default async function ApprovalsPage() {
  let entries: InboxEntry[] = [];
  let error: string | null = null;

  try {
    const [approvals, pipelineReviews] = await Promise.all([api.listApprovals(), api.listPipelineReviews()]);
    const approvalEntries = await Promise.all(approvals.map(toEntry));
    entries = [
      ...approvalEntries,
      ...pipelineReviews.map((review): InboxEntry => ({ kind: "pipeline_review", id: `review-${review.id}`, review })),
    ];
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Aprobaciones y decisiones"
        description="Centro de control humano para las acciones sensibles de AMAZONA: todo gasto externo simulado requiere aprobación humana explícita, y las ejecuciones de riesgo del pipeline (ADR 0006) entran en la misma bandeja."
      />

      <KillSwitchControl />

      {error ? <ApiErrorAlert message={error} /> : <ApprovalsInbox entries={entries} />}
    </div>
  );
}
