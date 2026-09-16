import { api, type Approval, type Decision, type Project } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { ApprovalCard } from "@/components/approval-card";
import { Card, CardContent } from "@/components/ui/card";

interface EnrichedApproval {
  approval: Approval;
  decision: Decision | null;
  project: Project | null;
}

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
  let items: EnrichedApproval[] = [];
  let error: string | null = null;

  try {
    const approvals = await api.listApprovals();
    items = await Promise.all(approvals.map(enrich));
    items.sort((a, b) => (a.approval.status === "PENDING" ? -1 : 1) - (b.approval.status === "PENDING" ? -1 : 1));
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <PageHeader
        title="Approvals"
        description="Every simulated external spend requires explicit human approval before it can proceed."
      />

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
          {items.map(({ approval, decision, project }) => (
            <ApprovalCard key={approval.id} approval={approval} decision={decision} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
