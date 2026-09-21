import { api, type Decision, type Project, type Task } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { ProjectsPortfolio, type PortfolioProject } from "./projects-portfolio";

async function loadPortfolioItem(project: Project): Promise<PortfolioProject> {
  const [decisions, tasks] = await Promise.all([
    api.listDecisionsForProject(project.id).catch(() => [] as Decision[]),
    api.listTasks(project.id).catch(() => [] as Task[]),
  ]);
  return { project, decision: decisions[0] ?? null, tasks };
}

export default async function ProjectsPage() {
  let items: PortfolioProject[] = [];
  let error: string | null = null;

  try {
    const projects = await api.listProjects();
    items = await Promise.all(projects.map(loadPortfolioItem));
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Proyectos"
        description="Cartera de oportunidades: cada validación de producto orquestada por el Director ejecutivo, con su estado, su salud y el avance de sus tareas."
      />

      {error ? <ApiErrorAlert message={error} /> : <ProjectsPortfolio items={items} />}
    </div>
  );
}
