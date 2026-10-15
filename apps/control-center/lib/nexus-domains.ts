import { teamOf } from "./agents.ts";

// Los dominios del grafo de agentes del Director ejecutivo (M47, Commit 4): estructura del grafo, NO datos. Antes vivían en un módulo de
// demostración junto a datos inventados (tareas, progreso y handoffs); ese módulo se retiró y aquí solo queda lo estructural: el orden y la
// descripción de los ocho dominios del Anexo A y los iconos con los que se dibujan.

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

/** El dominio de un agente según su rol del registro. Un rol sin equipo conocido cae en Operaciones (el mismo reparto de siempre). */
export function domainOfRole(role: string): DomainKey {
  const team = teamOf(role);
  return (DOMAINS as readonly string[]).includes(team) ? (team as DomainKey) : "Operaciones";
}

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

/** Icono de cada dominio, por clave (el componente lo resuelve la capa visual: la lib no conoce lucide). Son los del mockup. */
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

/** Icono de cada agente según el hueco que ocupa en su dominio. Si un dominio tuviera más agentes de los previstos, los siguientes
 * heredan el icono de su dominio. */
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
