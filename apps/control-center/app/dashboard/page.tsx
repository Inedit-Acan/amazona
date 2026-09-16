import Link from "next/link";
import { api, type Agent, type Approval, type Project } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default async function DashboardPage() {
  let agents: Agent[] = [];
  let approvals: Approval[] = [];
  let projects: Project[] = [];
  let error: string | null = null;

  try {
    [agents, approvals, projects] = await Promise.all([api.listAgents(), api.listApprovals(), api.listProjects()]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const pendingApprovals = approvals.filter((a) => a.status === "PENDING");
  const availableAgents = agents.filter((a) => a.status === "AVAILABLE");

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Simulated business state: no real money, orders, suppliers, or tax submissions."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Projects</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">{projects.length}</CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Agents online</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">
                {availableAgents.length}/{agents.length}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Pending approvals</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">{pendingApprovals.length}</CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">New objective</CardTitle>
              </CardHeader>
              <CardContent>
                <Button size="sm" nativeButton={false} render={<Link href="/ceo" />}>
                  Launch validation
                </Button>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Approvals awaiting a decision</CardTitle>
            </CardHeader>
            <CardContent>
              {pendingApprovals.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nothing waiting on human approval right now.</p>
              ) : (
                <ul className="divide-y">
                  {pendingApprovals.map((approval) => (
                    <li key={approval.id} className="flex items-center justify-between gap-4 py-3">
                      <div>
                        <p className="text-sm font-medium">{approval.action}</p>
                        <p className="text-xs text-muted-foreground">
                          Amount: {approval.amount != null ? `$${approval.amount.toFixed(2)}` : "n/a"} (simulated)
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <StatusBadge status={approval.status} />
                        <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/approvals" />}>
                          Review
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
