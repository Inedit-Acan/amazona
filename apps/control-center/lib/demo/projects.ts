// DATOS DE DEMOSTRACIÓN — pantalla de Proyectos.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que la
// cartera se vea como el mockup mientras el backend no la da: un proyecto del
// backend es un grafo de tareas del Director ejecutivo sin producto, mercado,
// fase de negocio, salud ni beneficio, y hoy no hay ninguno creado. Cada
// producto real se convierte en un proyecto con sus datos reales y el resto de
// la cartera son proyectos de ejemplo deterministas. Sustituir cuando existan
// los endpoints (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 8).

export const PROJECT_CODE_PREFIX = "AMZ-";

/** Proyectos de ejemplo que completan la cartera (los reales van antes). */
export const DEMO_PROJECTS = [
  { name: "AirPure X2", category: "home", market: "eu", phase: "legal", daysAgo: 12, profit: 1930, health: 74, status: "En curso" },
  { name: "EcoBottle", category: "accessories", market: "eu", phase: "operations", daysAgo: 17, profit: 1110, health: 91, status: "En curso" },
  { name: "SolarCharge", category: "electronics", market: "us", phase: "economics", daysAgo: 21, profit: 640, health: 46, status: "En riesgo" },
  { name: "SmartFeeder", category: "home", market: "eu", phase: "suppliers", daysAgo: 25, profit: null, health: 58, status: "En curso" },
  { name: "HomeCam", category: "electronics", market: "eu", phase: "research", daysAgo: 33, profit: 1240, health: 66, status: "En curso" },
  { name: "AirDesk", category: "home", market: "mx", phase: "store", daysAgo: 38, profit: null, health: 40, status: "Pausado" },
  { name: "PetTracker", category: "accessories", market: "eu", phase: "scale", daysAgo: 83, profit: 1980, health: 95, status: "Cerrado" },
  { name: "TravelKit", category: "accessories", market: "us", phase: "marketing", daysAgo: 45, profit: 870, health: 62, status: "En riesgo" },
  { name: "DeskLamp Pro", category: "home", market: "eu", phase: "operations", daysAgo: 52, profit: 1460, health: 88, status: "En curso" },
] as const;

/** Proyectos cerrados de la demostración (ya no cuentan como activos). */
export const DEMO_CLOSED_PROJECTS = [
  { name: "GlowBand", category: "accessories", market: "eu", daysAgo: 120, profit: 620, health: 71 },
  { name: "AquaFilter", category: "home", market: "eu", daysAgo: 150, profit: 0, health: 38 },
] as const;

/** Documentos del proyecto (no hay gestor documental). */
export const DEMO_DOCUMENTS = [
  { name: "Ficha de producto", type: "PDF", state: "Generado" },
  { name: "Cotización del proveedor", type: "PDF", state: "Generado" },
  { name: "Análisis económico", type: "XLSX", state: "Generado" },
  { name: "Informe legal", type: "PDF", state: "Generado" },
  { name: "Brief de campaña", type: "DOC", state: "Borrador" },
  { name: "Contrato con el proveedor", type: "PDF", state: "Pendiente" },
];

/** Minutos que lleva pendiente la próxima decisión. */
export const DEMO_DECISION_MINUTES = 23;

/** Reparto del capital expuesto: parte del pedido que AMAZONA adelanta al proveedor. */
export const DEMO_SUPPLIER_ADVANCE = 0.45;

/** Desviación de lo real frente a lo previsto en cada métrica (determinista por proyecto). */
export const DEMO_ACTUAL_SPREAD = 0.12;
