import { api } from "@/lib/api-server";
import { type Agent, type AuditEntry, type Decision, type Project, type Task } from "@/lib/api";
import type { ProjectSource } from "@/lib/projects-view";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { PROJECTS_DESCRIPTION, PROJECTS_TITLE } from "./copy";
import { ProjectsWorkspace } from "./projects-workspace";

// M45, Commit 11: esta pantalla lee **sólo proyectos del backend**. Antes leía además los doce primeros productos del
// catálogo y presentaba cada uno como un proyecto; un producto no es un proyecto, así que ese tope desaparece con la
// dependencia que lo justificaba.
//
// Por cada proyecto: su grafo de tareas, su decisión y la auditoría de su ejecución. La auditoría se pide POR
// CORRELACIÓN —el Director ejecutivo usa una sola correlación para el proyecto, sus tareas y su decisión
// (`ceo/orchestrator.py`)—, no leyendo el registro entero y filtrándolo: así la fecha de alta y la actividad son las de
// este proyecto y de ningún otro.

export default async function ProjectsPage({ searchParams }: PageProps<"/projects">) {
  const params = await searchParams;
  const requested = Array.isArray(params.proyecto) ? params.proyecto[0] : params.proyecto;

  let projects: Project[] = [];
  let error: string | null = null;
  try {
    projects = await api.listProjects();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  const sources: ProjectSource[] = await Promise.all(
    projects.map(async (project) => {
      const tasks = await api.listTasks(project.id).catch(() => [] as Task[]);
      const decision = (await api.listDecisionsForProject(project.id).catch(() => [] as Decision[]))[0] ?? null;
      const audit = decision
        ? await api.listAudit(decision.correlation_id).catch(() => [] as AuditEntry[])
        : ([] as AuditEntry[]);
      return { project, tasks, decision, audit };
    }),
  );

  const agents: Agent[] = await api.listAgents().catch(() => []);

  if (error) {
    return (
      <div>
        <PageHeader title={PROJECTS_TITLE} description={PROJECTS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return <ProjectsWorkspace sources={sources} agents={agents} initialSelection={requested} />;
}
