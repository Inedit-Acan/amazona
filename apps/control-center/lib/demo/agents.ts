// DATOS DE DEMOSTRACIÓN — pantalla de Agentes.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona: el
// registro de agentes no guarda descripción, evaluaciones, coste real, tarea en
// curso, herramientas, permisos ni histórico de versiones, y el
// `cost_profile.simulated_cost_per_task` que devuelve hoy es 0. Lo real —los
// agentes registrados y su log de ejecuciones— se usa siempre que existe.
// Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 9).

import type { Agent, AgentExecution } from "../api.ts";
import { demoRandom } from "./random.ts";

/** Qué hace cada agente, por rol del registro. */
export const ROLE_DESCRIPTIONS: Record<string, string> = {
  product: "Descubre productos y problemas con oportunidad comercial.",
  research: "Analiza demanda, competencia y tendencias de mercado.",
  supplier: "Encuentra y compara proveedores globales.",
  sourcing: "Analiza incoterms, transporte, aduanas y costes logísticos.",
  finance: "Calcula precio, margen, CAC, break-even y escenarios.",
  economics: "Analiza sensibilidad, capital expuesto y riesgo económico.",
  legal: "Certificaciones, seguridad y compliance de producto.",
  legal_compliance: "Analiza normativa de e-commerce, consumo y obligaciones legales.",
  ecommerce: "Crea y optimiza tiendas, landings y producto maestro.",
  marketplace: "Gestiona Amazon y otros marketplaces o canales.",
  marketing: "Planifica y ejecuta campañas, audiencias y creatividades.",
  operations: "Gestiona pedidos, fulfillment, tracking e incidencias.",
  cfo: "Finanzas corporativas, caja, presupuestos y forecast.",
};

/** Coste por ejecución (€) según el equipo del agente. */
export const COST_PER_RUN: Record<string, number> = {
  Investigación: 0.09,
  Abastecimiento: 0.12,
  Economía: 0.07,
  Legal: 0.08,
  Comercio: 0.06,
  Marketing: 0.11,
  Operaciones: 0.05,
  Finanzas: 0.1,
  Otros: 0.05,
};

/** Ejecuciones diarias por agente cuando el log todavía está vacío. */
export const DEMO_RUNS_PER_DAY = 14;

/** Latencia media (ms) de cada equipo en las ejecuciones de demostración. */
export const DEMO_LATENCY_MS: Record<string, number> = {
  "Investigación": 6200,
  Abastecimiento: 11_800,
  "Economía": 5600,
  Legal: 8100,
  Comercio: 9200,
  Marketing: 12_100,
  Operaciones: 9700,
  Finanzas: 7800,
  Otros: 7000,
};

/** Tasa de éxito de cada agente en las ejecuciones de demostración (0,96–0,995). */
export function demoSuccessRate(agentId: string): number {
  return 0.96 + demoRandom(agentId, "success") * 0.035;
}

/** Log de ejecuciones de demostración: el backend todavía no registra ninguna.
 * Determinista por agente, día e índice, para que la pantalla no cambie sola. */
export function demoExecutions(
  agents: Pick<Agent, "id" | "role" | "capabilities">[],
  teamOf: (role: string) => string,
  now: number,
  days: number,
): AgentExecution[] {
  const DAY_MS = 86_400_000;
  const dayStart = now - (now % DAY_MS);
  const rows: AgentExecution[] = [];
  for (const agent of agents) {
    const team = teamOf(agent.role);
    const latency = DEMO_LATENCY_MS[team] ?? DEMO_LATENCY_MS.Otros;
    const successRate = demoSuccessRate(agent.id);
    for (let offset = -(days - 1); offset <= 0; offset++) {
      const runs = Math.round(DEMO_RUNS_PER_DAY * (0.6 + demoRandom(agent.id, `runs-${offset}`) * 0.8));
      for (let k = 0; k < runs; k++) {
        const seed = `${agent.id}-${offset}-${k}`;
        // Las de hoy solo hasta la hora actual; las de días pasados, repartidas por el día.
        const span = offset === 0 ? now - dayStart : DAY_MS;
        const at = dayStart + offset * DAY_MS + Math.floor(((k + 0.5) / runs) * span);
        rows.push({
          id: `demo-exec-${seed}`,
          agent_id: agent.id,
          capability: agent.capabilities[0] ?? "run",
          duration_ms: Math.round(latency * (0.7 + demoRandom(seed, "latency") * 0.6)),
          success: demoRandom(seed, "ok") < successRate,
          correlation_id: `demo-${seed}`,
          created_at: new Date(at).toISOString(),
        });
      }
    }
  }
  return rows;
}

/** Tarea en curso de ejemplo por equipo (el backend no la expone). */
export const CURRENT_TASKS: Record<string, string[]> = {
  Investigación: ["Analizando candidatos", "Revisando tendencias", "Comparando nichos"],
  Abastecimiento: ["Contactando proveedores", "Comparando cotizaciones", "Calculando ruta"],
  Economía: ["Recalculando escenarios", "Revisando márgenes", "Simulando sensibilidad"],
  Legal: ["Revisando documentación", "Comprobando certificaciones", "Consultando normativa"],
  Comercio: ["Optimizando landing", "Generando listado", "Revisando SEO"],
  Marketing: ["Optimizando campañas", "Generando creatividades", "Ajustando audiencias"],
  Operaciones: ["Actualizando tracking", "Revisando incidencias", "Coordinando proveedor"],
  Finanzas: ["Calculando forecast", "Cerrando el mes", "Revisando presupuesto"],
  Otros: ["Procesando tareas"],
};

/** Herramientas y permisos de cada agente (no hay gestor de permisos). */
export const DEMO_TOOLS: Record<string, string[]> = {
  Investigación: ["Búsqueda web", "Índice de tendencias", "Catálogo interno"],
  Abastecimiento: ["Directorio de proveedores", "Calculadora logística", "Correo saliente"],
  Economía: ["Modelo económico", "Catálogo de costes"],
  Legal: ["Fuentes regulatorias", "Almacén documental"],
  Comercio: ["Generador de contenido", "API de tienda", "API de marketplace"],
  Marketing: ["Generador creativo", "Estimador de audiencias"],
  Operaciones: ["Tracking de transportistas", "Bandeja de incidencias"],
  Finanzas: ["Modelo financiero", "BudgetEngine"],
  Otros: ["Herramientas básicas"],
};

/** Umbrales de las alertas de la flota. */
export const ALERT_THRESHOLDS = {
  /** Tasa de error por agente que dispara aviso. */
  errorRate: 0.03,
  /** Latencia media (ms) que se considera lenta. */
  latencyMs: 12_000,
  /** Desvío de coste sobre la media de la flota. */
  costSpread: 0.3,
};

/** Notas de versión de ejemplo (el backend solo guarda la versión actual). */
export const DEMO_VERSION_NOTES = [
  "Ajuste de prompts y validación de salida",
  "Nuevo criterio de puntuación",
  "Corrección de reintentos",
  "Mejora de latencia",
];

/** Recursos del panel lateral (sin backend detrás). */
export const DEMO_RESOURCES = [
  { key: "docs", title: "Documentación de agentes", detail: "Guías y buenas prácticas" },
  { key: "eval", title: "Evaluar un agente", detail: "Ejecutar test de evaluación" },
  { key: "version", title: "Crear nueva versión", detail: "Clonar y configurar" },
  { key: "permissions", title: "Gestión de permisos", detail: "Herramientas y accesos" },
];

/** Puntuación de evaluación (0–100) determinista por agente. */
export function demoEvalScore(agentId: string): number {
  return 88 + Math.round(demoRandom(agentId, "eval") * 11);
}

/** Progreso de la tarea en curso (0–1) determinista por agente. */
export function demoTaskProgress(agentId: string): number {
  return 0.45 + demoRandom(agentId, "progress") * 0.5;
}

/** Índice de la tarea en curso dentro de las de su equipo. */
export function demoTaskIndex(agentId: string, options: number): number {
  return Math.min(options - 1, Math.floor(demoRandom(agentId, "task") * options));
}
