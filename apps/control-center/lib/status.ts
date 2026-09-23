import type { DetailedHealth } from "./api.ts";

// El backend expone una comprobación de salud (`/health/detailed`: base de datos,
// migración y si Supabase está configurado), el log de ejecuciones de agentes y
// los incidentes registrados a mano. No hay uptime, percentiles, colas, cron,
// integraciones, despliegues ni costes. Este módulo solo traduce esa señal real:
// qué servicios del mapa se pueden afirmar y cuál es el estado general. Lo que
// falta lo rellena lib/demo/status.ts y la pantalla lo declara.

export type ServiceState = "operational" | "down" | "no_signal";

export interface HealthSignal {
  apiReachable: boolean;
  /** Tiempo de la petición de salud desde el servidor del frontend (una sola medida). */
  latencyMs: number | null;
  health: Pick<DetailedHealth, "database" | "supabase_configured">;
}

/** Señal real de los agentes, sacada del log de ejecuciones (`AgentExecutionLog`). */
export interface WorkerSignal {
  runs: number;
  failures: number;
  /** Duración media (ms) de esas ejecuciones; null si no hay ninguna. */
  avgDurationMs: number | null;
}

export interface RealSignal {
  state: ServiceState;
  /** Latencia medida de verdad en esta carga; null si no se mide. */
  measuredMs: number | null;
  note: string;
}

/** Los servicios del mapa de los que sí hay señal real: el frontend (esta página
 * se ha renderizado), la API (responde a la comprobación de salud y se cronometra),
 * Postgres y la configuración de Supabase (Auth y Storage), y los workers de
 * agentes (su log de ejecuciones). Los otros doce servicios del mockup no tienen
 * telemetría y se rellenan con datos de demostración. */
export function realSignals(signal: HealthSignal, workers: WorkerSignal): Record<string, RealSignal> {
  const { apiReachable, latencyMs, health } = signal;
  const supabase: RealSignal = {
    state: !apiReachable ? "no_signal" : health.supabase_configured ? "operational" : "no_signal",
    measuredMs: null,
    note: !apiReachable
      ? "Sin respuesta del backend."
      : health.supabase_configured
        ? "Supabase está configurado; no se comprueba su disponibilidad."
        : "Supabase no está configurado en este entorno.",
  };
  return {
    frontend: { state: "operational", measuredMs: null, note: "Esta página se ha renderizado." },
    api: {
      state: apiReachable ? "operational" : "down",
      measuredMs: apiReachable ? latencyMs : null,
      note: apiReachable ? "Respondió a la comprobación de salud." : "No se pudo contactar con el backend.",
    },
    postgres: {
      state: !apiReachable ? "no_signal" : health.database === "ok" ? "operational" : "down",
      measuredMs: null,
      note: !apiReachable
        ? "Sin respuesta del backend."
        : health.database === "ok"
          ? "El backend puede consultarla."
          : "El backend no puede consultarla.",
    },
    auth: supabase,
    storage: supabase,
    workers: {
      state: workers.runs === 0 ? "no_signal" : workers.failures === workers.runs ? "down" : "operational",
      measuredMs: workers.avgDurationMs,
      note:
        workers.runs === 0
          ? "Todavía no hay ejecuciones de agentes registradas."
          : `${workers.runs} ejecuciones registradas, ${workers.failures} fallidas.`,
    },
  };
}

/** Resumen de las ejecuciones reales de agentes en la ventana mirada. */
export function workerSignal(executions: { success: boolean; duration_ms: number }[]): WorkerSignal {
  const runs = executions.length;
  return {
    runs,
    failures: executions.filter((e) => !e.success).length,
    avgDurationMs: runs > 0 ? executions.reduce((sum, e) => sum + e.duration_ms, 0) / runs : null,
  };
}

export interface OverallStatus {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estado general a partir de la señal real: backend caído > base de datos con error >
 * incidentes abiertos > operativo. «Operativo» solo habla de los servicios con señal. */
export function overallStatus(input: { signal: HealthSignal; openIncidents: number }): OverallStatus {
  const { signal, openIncidents } = input;
  if (!signal.apiReachable) {
    return { title: "Backend caído", detail: "El frontend no puede contactar con la API: nada de lo que ves aquí es reciente.", tone: "bad" };
  }
  if (signal.health.database !== "ok") {
    return { title: "Incidencia en la base de datos", detail: "El backend responde pero no puede consultar la base de datos.", tone: "bad" };
  }
  if (openIncidents > 0) {
    return {
      title: `${openIncidents} incidente${openIncidents === 1 ? "" : "s"} activo${openIncidents === 1 ? "" : "s"}`,
      detail: "Hay incidentes abiertos, registrados a mano.",
      tone: "warn",
    };
  }
  return {
    title: "Sistema operativo",
    detail: "Los servicios con telemetría responden. El resto se enseña con datos de demostración.",
    tone: "ok",
  };
}
