import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, api, type Decision, type Project, type Task } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { StatusChip } from "@/components/status-chip";
import { ProjectHealth } from "@/components/project-health";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function outputSummary(task: Task): string {
  if (task.status === "FAILED") return task.error ?? "Failed";
  const output = task.output as { recommendation?: string; confidence?: number } | null;
  if (!output?.recommendation) return "—";
  return `${output.recommendation}${output.confidence != null ? ` (${Math.round(output.confidence * 100)}%)` : ""}`;
}

export default async function ProjectDetailPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;

  let project: Project;
  try {
    project = await api.getProject(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    return (
      <div>
        <PageHeader title="Project" />
        <ApiErrorAlert message={err instanceof Error ? err.message : "Unknown error"} />
      </div>
    );
  }

  const [tasks, decisions] = await Promise.all([
    api.listTasks(project.id).catch(() => [] as Task[]),
    api.listDecisionsForProject(project.id).catch(() => [] as Decision[]),
  ]);
  const decision = decisions[0];

  return (
    <div className="space-y-6">
      <PageHeader title={project.name} description={project.id} />

      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Project status</span>
        <StatusChip status={project.status} />
      </div>

      <Card>
        <CardContent className="pt-6">
          <ProjectHealth decision={decision ?? null} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Task graph</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Task</TableHead>
                <TableHead>Capability</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TableRow key={task.id}>
                  <TableCell className="font-medium">{task.name.replace(/_/g, " ")}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{task.capability}</TableCell>
                  <TableCell>
                    <StatusChip status={task.status} />
                  </TableCell>
                  <TableCell className="text-sm">{outputSummary(task)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {decision ? (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>CEO decision</CardTitle>
              <StatusChip status={decision.status} />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3 text-sm">
              <div>
                <p className="text-muted-foreground">Opportunity score</p>
                <p className="font-medium">
                  {decision.opportunity_score != null ? decision.opportunity_score.toFixed(2) : "—"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Confidence</p>
                <p className="font-medium">{decision.confidence != null ? decision.confidence.toFixed(2) : "—"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Correlation ID</p>
                <Link
                  href={`/audit?correlation_id=${decision.correlation_id}`}
                  className="truncate font-mono text-xs text-primary underline underline-offset-4"
                >
                  {decision.correlation_id}
                </Link>
              </div>
            </div>
            {decision.rationale ? <p className="text-sm text-muted-foreground">{decision.rationale}</p> : null}

            <div>
              <p className="mb-2 text-sm font-medium">Evidence</p>
              <ul className="space-y-2">
                {decision.evidence.map((e, i) => (
                  <li key={i} className="rounded-md border bg-muted/30 p-3 text-sm">
                    <p className="font-medium capitalize">{e.source.replace(/_/g, " ")}</p>
                    <p className="text-muted-foreground">{e.summary}</p>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
