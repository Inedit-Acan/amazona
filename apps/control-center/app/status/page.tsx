import { ApiError, api, type Agent, type AgentExecution, type DetailedHealth, type Incident } from "@/lib/api";
import type { HealthSignal } from "@/lib/status";
import { StatusWorkspace } from "./status-workspace";

/** La comprobación de salud se mide desde el servidor del frontend: una sola medida, no un percentil. */
async function fetchHealth(): Promise<HealthSignal & { migration: string | null }> {
  const started = Date.now();
  try {
    const health = await api.getHealth();
    return { apiReachable: true, latencyMs: Date.now() - started, health, migration: health.migration };
  } catch (err) {
    if (err instanceof ApiError) {
      try {
        // /health/detailed responde 503 con el mismo cuerpo cuando la base de datos falla
        const health = JSON.parse(err.message) as DetailedHealth;
        return { apiReachable: true, latencyMs: Date.now() - started, health, migration: health.migration };
      } catch {
        // cae al estado de backend inalcanzable
      }
    }
    return { apiReachable: false, latencyMs: null, health: { database: "error", supabase_configured: false }, migration: null };
  }
}

export default async function StatusPage() {
  const [health, executions, incidents, agents] = await Promise.all([
    fetchHealth(),
    // null = la petición falló: no es lo mismo que «cero» y no se muestra como tal
    api.listAgentExecutions().catch((): AgentExecution[] | null => null),
    api.listIncidents().catch((): Incident[] | null => null),
    api.listAgents().catch((): Agent[] => []),
  ]);
  const { migration, ...signal } = health;

  // El instante se fija en el servidor: las colas, las series de 24 h y los «hace
  // X» de demostración se calculan con él y el cliente hidrata exactamente lo mismo.
  const now = new Date().getTime();

  return (
    <StatusWorkspace
      signal={signal}
      migration={migration}
      agents={agents}
      executions={executions}
      incidents={incidents}
      now={now}
    />
  );
}
