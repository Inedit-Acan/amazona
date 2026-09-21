import type { DetailedHealth } from "./api.ts";

// El backend expone una comprobación de salud (`/health/detailed`: base de datos,
// migración y si Supabase está configurado). No hay uptime, percentiles, colas,
// cron, integraciones, despliegues ni costes. Este módulo solo traduce esa señal
// real; lo demás se declara «sin telemetría» en vez de inventarse.

export type ServiceState = "operational" | "down" | "no_signal";

export interface ServiceRow {
  id: string;
  name: string;
  state: ServiceState;
  /** Latencia medida de esta comprobación (ms), si se midió. */
  latencyMs: number | null;
  note: string;
}

export interface HealthSignal {
  apiReachable: boolean;
  /** Tiempo de la petición de salud desde el servidor del frontend (una sola medida). */
  latencyMs: number | null;
  health: Pick<DetailedHealth, "database" | "supabase_configured">;
}

/** Los servicios de la spec (§9.5) de los que sí hay señal real: el frontend (esta
 * página se ha renderizado), la API (responde a la comprobación), la base de datos y la
 * configuración de Supabase. Los demás no se listan como operativos. */
export function serviceRows(signal: HealthSignal): ServiceRow[] {
  const { apiReachable, latencyMs, health } = signal;
  return [
    { id: "frontend", name: "Frontend", state: "operational", latencyMs: null, note: "Esta página se ha renderizado." },
    {
      id: "api",
      name: "API (backend)",
      state: apiReachable ? "operational" : "down",
      latencyMs: apiReachable ? latencyMs : null,
      note: apiReachable ? "Respondió a la comprobación de salud." : "No se pudo contactar con el backend.",
    },
    {
      id: "database",
      name: "Base de datos",
      state: !apiReachable ? "no_signal" : health.database === "ok" ? "operational" : "down",
      latencyMs: null,
      note: !apiReachable ? "Sin respuesta del backend." : health.database === "ok" ? "El backend puede consultarla." : "El backend no puede consultarla.",
    },
    {
      id: "supabase",
      name: "Supabase (Auth / Storage)",
      state: !apiReachable ? "no_signal" : health.supabase_configured ? "operational" : "no_signal",
      latencyMs: null,
      note: !apiReachable
        ? "Sin respuesta del backend."
        : health.supabase_configured
          ? "Está configurado; no se comprueba su disponibilidad."
          : "No está configurado en este entorno.",
    },
  ];
}

export function serviceSummary(rows: ServiceRow[]): { operational: number; down: number; withSignal: number } {
  const operational = rows.filter((r) => r.state === "operational").length;
  const down = rows.filter((r) => r.state === "down").length;
  return { operational, down, withSignal: operational + down };
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
    title: "Operativo",
    detail: "Los servicios con telemetría responden. El resto de servicios todavía no tiene telemetría.",
    tone: "ok",
  };
}
