// DATOS DE DEMOSTRACIÓN — pantalla de Aprobaciones y decisiones.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que la
// bandeja se vea como el mockup mientras el backend no la llena: una aprobación
// real solo tiene acción, importe, vencimiento y estado, no lleva tipo,
// severidad, proyecto, agente solicitante, análisis, hallazgos ni impacto, y hoy
// no hay ninguna creada. Las solicitudes de demostración se construyen sobre
// productos, análisis y agentes reales. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 10).

import { demoRandom } from "./random.ts";

export type RequestKind = "marketing" | "suppliers" | "operations" | "commerce" | "agents" | "legal" | "finance";

export const KIND_LABELS: Record<RequestKind, string> = {
  marketing: "Marketing",
  suppliers: "Proveedores",
  operations: "Operaciones",
  commerce: "Lanzamientos",
  agents: "Agentes",
  legal: "Legal",
  finance: "Finanzas",
};

export type Severity = "Crítica" | "Alta" | "Media" | "Baja";

export const SEVERITY_ORDER: Severity[] = ["Crítica", "Alta", "Media", "Baja"];

export interface RequestTemplate {
  key: string;
  kind: RequestKind;
  title: string;
  severity: Severity;
  /** Horas desde que se solicitó. */
  agedHours: number;
  /** Etiqueta del importe en la lista («Presupuesto», «Inversión»…). */
  amountLabel: string;
  /** Qué autoriza la solicitud, para el impacto de la decisión. */
  approves: string;
}

/** Las solicitudes que el mockup enseña, en su orden. El importe y el proyecto
 * salen de datos reales cuando existen (ver lib/approvals-view.ts). */
export const REQUEST_TEMPLATES: RequestTemplate[] = [
  { key: "campaign", kind: "marketing", title: "Campaña de lanzamiento", severity: "Crítica", agedHours: 0.4, amountLabel: "Presupuesto", approves: "la activación de la campaña" },
  { key: "supplier", kind: "suppliers", title: "Nuevo proveedor", severity: "Alta", agedHours: 1, amountLabel: "Volumen inicial", approves: "el alta del proveedor" },
  { key: "stock", kind: "operations", title: "Stock anticipado", severity: "Crítica", agedHours: 2, amountLabel: "Inversión", approves: "la compra anticipada de stock" },
  { key: "amazon", kind: "commerce", title: "Activación de canal Amazon", severity: "Media", agedHours: 3, amountLabel: "Coste directo", approves: "la publicación del listado en Amazon" },
  { key: "agent", kind: "agents", title: "Deploy nueva versión de agente", severity: "Media", agedHours: 5, amountLabel: "Infraestructura", approves: "el despliegue de la nueva versión" },
  { key: "legal", kind: "legal", title: "Excepción legal", severity: "Media", agedHours: 26, amountLabel: "Sin coste", approves: "la excepción sobre el requisito legal" },
  { key: "refund", kind: "operations", title: "Reembolso extraordinario", severity: "Baja", agedHours: 30, amountLabel: "Importe", approves: "el reembolso al cliente" },
];

/** Horas de SLA por severidad: por debajo de eso, la solicitud «vence pronto». */
export const SLA_HOURS: Record<Severity, number> = { "Crítica": 4, Alta: 12, Media: 24, Baja: 48 };

/** Solicitudes ya resueltas de los últimos 30 días, para las estadísticas. */
export const RESOLVED_STATS = {
  approved: 13,
  rejected: 3,
  inReview: 4,
  withdrawn: 2,
  expired: 3,
  /** Minutos que se tarda de media en resolver. */
  averageMinutes: 18,
  /** Variación del tiempo medio respecto al periodo anterior. */
  averageTrend: -0.32,
  /** Resueltas por día de los últimos 7 días (para la tendencia). */
  daily: [14, 17, 15, 21, 19, 24, 18],
};

/** Detalle de la campaña que el agente de marketing no expone todavía. */
export const CAMPAIGN_DETAIL = { periodDays: 14, objective: "Lanzamiento inicial", minRoas: 2.3 };

/** Volumen inicial del proveedor y stock anticipado (unidades). */
export const DEMO_UNITS = { supplierFirstOrder: 500, anticipatedStock: 400, refundAmount: 39.9 };

/** Coste de infraestructura del despliegue de un agente. */
export const DEMO_AGENT_DEPLOY_COST = 0;

/** Comentarios de ejemplo del hilo de una solicitud. */
export const DEMO_COMMENTS = [
  { author: "Iván SC", role: "Owner", text: "¿El CAC previsto aguanta si subimos el presupuesto un 20 %?" },
  { author: "CFO Controller", role: "Agente", text: "Con 1.800 € el CAC previsto sube a 5,9 €, todavía por debajo del máximo." },
];

/** Pasos del flujo de aprobación (el backend solo guarda un estado). */
export const APPROVAL_FLOW = [
  { key: "requested", label: "Solicitada por el agente" },
  { key: "validated", label: "Validaciones automáticas" },
  { key: "human", label: "Decisión humana" },
  { key: "executed", label: "Ejecución de la acción" },
];

/** Documentos adjuntos a la solicitud (no hay gestor documental). */
export const DEMO_DOCUMENTS = [
  { name: "Brief de campaña", type: "PDF" },
  { name: "Análisis económico", type: "XLSX" },
  { name: "Informe legal", type: "PDF" },
];

/** Minutos de antigüedad de un comentario, deterministas por solicitud. */
export function demoCommentMinutes(requestId: string, index: number): number {
  return 5 + Math.round(demoRandom(requestId, `comment-${index}`) * 90);
}
