import { api } from "@/lib/api-server";
import { ApiError, type DetailedHealth } from "@/lib/api";
import { listOf } from "@/lib/read-state";
import type { HealthSignal } from "@/lib/status";
import { readStatusPage, statusFailures } from "@/lib/status-reads";
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
  const [health, reads] = await Promise.all([fetchHealth(), readStatusPage(api)]);
  const { migration, ...signal } = health;

  // El instante se fija en el servidor: las colas, las series de 24 h y los «hace
  // X» de demostración se calculan con él y el cliente hidrata exactamente lo mismo.
  const now = new Date().getTime();

  // `listOf`: `null` si la lectura falló (cada tarjeta lo dice), `[]` solo si el backend dijo que estaba vacío.
  return (
    <StatusWorkspace
      signal={signal}
      migration={migration}
      agents={listOf(reads.agents)}
      executions={listOf(reads.executions)}
      incidents={listOf(reads.incidents)}
      jobs={listOf(reads.jobs)}
      pipelineRuns={listOf(reads.pipelineRuns)}
      apiUsage={listOf(reads.apiUsage)}
      failures={statusFailures(reads)}
      now={now}
    />
  );
}
