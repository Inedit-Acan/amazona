import { api, type AuditEntry } from "@/lib/api";
import type { ProjectByCorrelation } from "@/lib/audit";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { AuditWorkspace } from "./audit-workspace";

/** Tope de proyectos de los que se leen las decisiones para atribuir eventos: hoy no
 * hay un endpoint que dé el proyecto de un evento y cada proyecto cuesta una petición. */
const PROJECT_LOOKUP_LIMIT = 40;

export default async function AuditPage({ searchParams }: PageProps<"/audit">) {
  const { correlation_id } = await searchParams;
  const correlationId = Array.isArray(correlation_id) ? correlation_id[0] : correlation_id;

  let entries: AuditEntry[] = [];
  const projects: ProjectByCorrelation = {};
  let error: string | null = null;

  try {
    entries = await api.listAudit(correlationId);
    const projectList = await api.listProjects();
    const decisions = await Promise.all(
      projectList.slice(0, PROJECT_LOOKUP_LIMIT).map(async (project) => ({
        project,
        decisions: await api.listDecisionsForProject(project.id).catch(() => []),
      })),
    );
    for (const { project, decisions: list } of decisions) {
      for (const decision of list) projects[decision.correlation_id] = { id: project.id, name: project.name };
    }
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Auditoría y trazabilidad"
        description={
          correlationId
            ? `Mostrando todas las acciones registradas bajo el ID de correlación ${correlationId}.`
            : "Registro de las acciones relevantes de los agentes, el director ejecutivo y las personas, trazables por ID de correlación. La interfaz no permite editarlo ni borrarlo."
        }
      />

      {error ? <ApiErrorAlert message={error} /> : <AuditWorkspace entries={entries} projects={projects} correlationId={correlationId} />}
    </div>
  );
}
