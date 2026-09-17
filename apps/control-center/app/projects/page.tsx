import Link from "next/link";
import { api, type Project } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent } from "@/components/ui/card";

export default async function ProjectsPage() {
  let projects: Project[] = [];
  let error: string | null = null;

  try {
    projects = await api.listProjects();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <PageHeader title="Projects" description="Every product-validation run the CEO has orchestrated." />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : projects.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No projects yet. Launch one from the{" "}
            <Link href="/ceo" className="font-medium text-primary underline underline-offset-4">
              CEO
            </Link>{" "}
            page.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {projects.map((project) => (
            <Link key={project.id} href={`/projects/${project.id}`}>
              <Card className="transition-colors hover:bg-muted/50">
                <CardContent className="flex items-center justify-between gap-4 py-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{project.name}</p>
                    <p className="truncate font-mono text-xs text-muted-foreground">{project.id}</p>
                  </div>
                  <StatusChip status={project.status} />
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
