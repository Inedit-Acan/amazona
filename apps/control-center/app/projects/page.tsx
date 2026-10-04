import { api } from "@/lib/api-server";
import { type Agent, type AuditEntry, type Decision, type Project, type Task } from "@/lib/api";
import type { ProjectSource, ReadName } from "@/lib/projects-view";
import { settle } from "@/lib/revenue-view";
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
      // Un error de lectura NO es un dato: no se convierte en `[]`. Cada lectura que falla se anota, y la pantalla dice
      // «No se pudo leer» en lugar de «sin tareas», «sin decisión» o «sin fecha».
      const [tasksRead, decisionsRead] = await Promise.all([
        settle<Task[]>(() => api.listTasks(project.id)),
        settle<Decision[]>(() => api.listDecisionsForProject(project.id)),
      ]);
      const decision = decisionsRead.ok ? (decisionsRead.data[0] ?? null) : null;
      const auditRead = decision ? await settle<AuditEntry[]>(() => api.listAudit(decision.correlation_id)) : null;
      const unread: ReadName[] = [
        ...(tasksRead.ok ? [] : (["tasks"] as const)),
        ...(decisionsRead.ok ? [] : (["decision"] as const)),
        ...(auditRead === null || auditRead.ok ? [] : (["audit"] as const)),
      ];
      return {
        project,
        tasks: tasksRead.ok ? tasksRead.data : [],
        decision,
        audit: auditRead?.ok ? auditRead.data : [],
        unread,
      };
    }),
  );

  const agentsRead = await settle<Agent[]>(() => api.listAgents());
  const agents = agentsRead.ok ? agentsRead.data : [];
  const agentsUnread = !agentsRead.ok;

  if (error) {
    return (
      <div>
        <PageHeader title={PROJECTS_TITLE} description={PROJECTS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return <ProjectsWorkspace sources={sources} agents={agents} agentsUnread={agentsUnread} initialSelection={requested} />;
}
