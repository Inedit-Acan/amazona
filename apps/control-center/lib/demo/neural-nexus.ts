// DATOS DE DEMOSTRACIÓN — grafo de agentes del Director ejecutivo (Neural Nexus).
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el grafo
// se vea como el mockup mientras el backend no los proporciona: el registro de
// agentes no guarda tarea en curso ni progreso, no hay bus de eventos ni
// handoffs entre agentes, y el «Decision Engine» no publica latencia, eventos
// activos ni decisiones recientes. Deterministas por agente y por hora
// (demoRandom). Lo real —los 13 agentes registrados con su estado, el log de
// ejecuciones y la decisión del CEO con sus evidencias— se usa siempre que
// existe. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, Director ejecutivo).

import { demoRandom } from "./random.ts";

/** Los 8 dominios, en el orden horario de la especificación (§7.3). */
export const DOMAINS = [
  "Investigación",
  "Abastecimiento",
  "Economía",
  "Legal",
  "Finanzas",
  "Operaciones",
  "Marketing",
  "Comercio",
] as const;

export type DomainKey = (typeof DOMAINS)[number];

export const DOMAIN_DESCRIPTION: Record<DomainKey, string> = {
  "Investigación": "Descubre productos y analiza demanda, competencia y tendencias.",
  Abastecimiento: "Encuentra proveedores y calcula logística, aduanas y plazos.",
  "Economía": "Precio, margen, punto de equilibrio, sensibilidad y riesgo económico.",
  Legal: "Normativa de producto, certificaciones y derecho de consumo.",
  Finanzas: "Caja, presupuesto, previsión y salud financiera.",
  Operaciones: "Pedidos, fulfillment, transporte e incidencias con clientes.",
  Marketing: "Campañas, audiencias, creatividades y coste de adquisición.",
  Comercio: "Tienda propia, listados y canales de venta.",
};

/** Roster canónico de la especificación (§6): dos agentes por dominio salvo
 * Marketing, Operaciones y Finanzas. Solo se usa cuando el registro está vacío;
 * con backend, los nombres y los estados son los de los agentes reales. */
export const CANONICAL_AGENTS: { id: string; label: string; domain: DomainKey }[] = [
  { id: "product-hunter", label: "Product Hunter", domain: "Investigación" },
  { id: "market-analyst", label: "Market Analyst", domain: "Investigación" },
  { id: "supplier-finder", label: "Supplier Finder", domain: "Abastecimiento" },
  { id: "trade-logistics-analyst", label: "Trade & Logistics Analyst", domain: "Abastecimiento" },
  { id: "unit-economics-analyst", label: "Unit Economics Analyst", domain: "Economía" },
  { id: "risk-analyst", label: "Risk Analyst", domain: "Economía" },
  { id: "product-compliance", label: "Product Compliance", domain: "Legal" },
  { id: "consumer-law", label: "Commerce & Consumer Law", domain: "Legal" },
  { id: "cfo-controller", label: "CFO / Financial Controller", domain: "Finanzas" },
  { id: "operations-customer", label: "Operations & Customer Service", domain: "Operaciones" },
  { id: "acquisition-agent", label: "Acquisition Agent", domain: "Marketing" },
  { id: "storefront-builder", label: "Storefront Builder", domain: "Comercio" },
  { id: "marketplace-channel", label: "Marketplace Channel", domain: "Comercio" },
];

/** Icono de cada dominio, por clave (el componente lo resuelve la capa visual:
 * la lib no conoce lucide). Son los del mockup. */
export const DOMAIN_ICON_KEY: Record<DomainKey, string> = {
  "Investigación": "search",
  Abastecimiento: "box",
  "Economía": "bar-chart",
  Legal: "scale",
  Finanzas: "database",
  Operaciones: "settings",
  Marketing: "megaphone",
  Comercio: "cart",
};

/** Icono de cada agente según el hueco que ocupa en su dominio, en el orden del
 * roster canónico. Si un dominio tuviera más agentes de los previstos, los
 * siguientes heredan el icono de su dominio. */
export const DOMAIN_AGENT_ICON_KEYS: Record<DomainKey, string[]> = {
  "Investigación": ["search", "trending"],
  Abastecimiento: ["box", "truck"],
  "Economía": ["calculator", "alert"],
  Legal: ["file", "shield"],
  Finanzas: ["chart-line"],
  Operaciones: ["headset"],
  Marketing: ["users"],
  Comercio: ["monitor", "store"],
};

/** Tarea en curso de ejemplo por dominio (el registro no la expone). */
export const DEMO_TASKS: Record<DomainKey, string[]> = {
  "Investigación": ["Comparando 18 nichos", "Revisando tendencias de búsqueda", "Puntuando candidatos"],
  Abastecimiento: ["Comparando 14 proveedores", "Calculando coste logístico", "Verificando certificados"],
  "Economía": ["Recalculando escenarios", "Simulando sensibilidad", "Revisando punto de equilibrio"],
  Legal: ["Comprobando normativa UE", "Revisando certificaciones", "Analizando derecho de consumo"],
  Finanzas: ["Cerrando previsión del mes", "Revisando presupuesto", "Actualizando caja"],
  Operaciones: ["Revisando incidencias abiertas", "Actualizando tracking", "Coordinando proveedor"],
  Marketing: ["Ajustando audiencias", "Generando creatividades", "Optimizando CAC"],
  Comercio: ["Optimizando listado", "Generando ficha de producto", "Revisando canal"],
};

/** Proyecto y progreso que enseña el HUD mientras no haya misión real. */
export const DEMO_PROJECT = { code: "AMZ-2026-003", progress: 0.68 };

/** Métricas del Decision Engine sin telemetría detrás. */
export const DEMO_CORE_METRICS = { activeEvents: 3, latencyMs: 1200, handoffs: 7, humanGates: 1 };

/** Handoffs de ejemplo entre agentes: solo se dibujan en modo Ejecución. */
export const DEMO_HANDOFFS: [string, string][] = [
  ["Investigación", "Abastecimiento"],
  ["Abastecimiento", "Economía"],
  ["Economía", "Legal"],
  ["Legal", "Comercio"],
  ["Comercio", "Marketing"],
];

/** Progreso (0–1) de la tarea en curso, determinista por agente. */
export function demoProgress(agentId: string): number {
  return Math.round((0.35 + demoRandom(agentId, "nexus-progress") * 0.6) * 100) / 100;
}

/** Índice de la tarea en curso dentro de las de su dominio. */
export function demoTaskIndex(agentId: string, options: number): number {
  return Math.min(options - 1, Math.floor(demoRandom(agentId, "nexus-task") * options));
}

/** Puntuación de evaluación (0–100) determinista por agente. */
export function demoEvaluation(agentId: string): number {
  return 86 + Math.round(demoRandom(agentId, "nexus-eval") * 13);
}
