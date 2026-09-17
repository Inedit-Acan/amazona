import { api, type Approval, type Decision, type PipelineReview, type Project } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { ApprovalCard } from "@/components/approval-card";
import { PipelineReviewCard } from "@/components/pipeline-review-card";
import { KillSwitchControl } from "@/components/kill-switch-control";
import { Card, CardContent } from "@/components/ui/card";

interface EnrichedApproval {
  approval: Approval;
  decision: Decision | null;
  project: Project | null;
}

type InboxItem =
  | { kind: "approval"; pending: boolean; item: EnrichedApproval }
  | { kind: "pipeline_review"; pending: boolean; item: PipelineReview };

async function enrich(approval: Approval): Promise<EnrichedApproval> {
  try {
    const decision = await api.getDecision(approval.decision_id);
    const project = await api.getProject(decision.project_id).catch(() => null);
    return { approval, decision, project };
  } catch {
    return { approval, decision: null, project: null };
  }
}

export default async function ApprovalsPage() {
  let items: InboxItem[] = [];
  let error: string | null = null;

  try {
    const [approvals, pipelineReviews] = await Promise.all([api.listApprovals(), api.listPipelineReviews()]);
    const enrichedApprovals = await Promise.all(approvals.map(enrich));

    items = [
      ...enrichedApprovals.map(
        (item): InboxItem => ({ kind: "approval", pending: item.approval.status === "PENDING", item }),
      ),
      ...pipelineReviews.map(
        (item): InboxItem => ({ kind: "pipeline_review", pending: item.status === "PENDING", item }),
      ),
    ];
    items.sort((a, b) => (a.pending === b.pending ? 0 : a.pending ? -1 : 1));
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Aprobaciones"
        description="Todo gasto externo simulado requiere aprobación humana explícita. Las ejecuciones de riesgo del pipeline (ADR 0006) entran en la misma bandeja."
      />

      <KillSwitchControl />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No approvals requested yet.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((entry) =>
            entry.kind === "approval" ? (
              <ApprovalCard
                key={`approval-${entry.item.approval.id}`}
                approval={entry.item.approval}
                decision={entry.item.decision}
                project={entry.item.project}
              />
            ) : (
              <PipelineReviewCard key={`pipeline-review-${entry.item.id}`} review={entry.item} />
            ),
          )}
        </div>
      )}
    </div>
  );
}
