// DATOS DE DEMOSTRACIÓN — pantalla de Auditoría y trazabilidad.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// registro se vea como el mockup mientras el backend no lo llena: una entrada
// real de `AuditLog` solo tiene actor, acción, recurso, estado antes/después, ID
// de correlación y fecha — no hay criticidad, resultado, proyecto, IP, user
// agent, evidencias, hash ni política de retención—, y hoy solo hay una decena
// de entradas. Lo real se usa siempre que existe. Sustituir cuando existan los
// endpoints (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 11).

import { demoRandom } from "./random.ts";

/** Eventos que se generan cada día de la ventana de demostración. */
export const EVENTS_PER_DAY = 60;
export const WINDOW_DAYS = 30;

export interface EventTemplate {
  /** Acción en el formato del backend (`approval.completed`). */
  action: string;
  title: string;
  detail: string;
  /** Rol del actor: se resuelve al agente real de ese rol cuando existe. */
  actorRole: string | null;
  actorFallback: string;
  result: "Éxito" | "Creado" | "Error";
  criticality: "Alta" | "Media" | "Baja";
  /** El evento se atribuye a un proyecto (producto) concreto. */
  hasProject: boolean;
}

export const EVENT_TEMPLATES: EventTemplate[] = [
  { action: "approval.completed", title: "Campaña aprobada", detail: "Presupuesto autorizado", actorRole: null, actorFallback: "Iván SC", result: "Éxito", criticality: "Alta", hasProject: true },
  { action: "cfo.budget_validated", title: "Presupuesto validado", detail: "Disponible en el periodo", actorRole: "cfo", actorFallback: "CFO Controller", result: "Éxito", criticality: "Media", hasProject: true },
  { action: "marketing.investment_requested", title: "Solicitud de inversión creada", detail: "Pendiente de aprobación", actorRole: "marketing", actorFallback: "Acquisition Agent", result: "Creado", criticality: "Media", hasProject: true },
  { action: "legal.gate_cleared", title: "Legal Gate aprobado", detail: "Sin restricciones para el mercado", actorRole: "legal", actorFallback: "Legal Agent", result: "Éxito", criticality: "Baja", hasProject: true },
  { action: "sourcing.supplier_evaluated", title: "Nuevo proveedor evaluado", detail: "Cotización comparada", actorRole: "supplier", actorFallback: "Supplier Finder", result: "Éxito", criticality: "Media", hasProject: true },
  { action: "config.agent_deployed", title: "Despliegue de nueva versión", detail: "Agente actualizado", actorRole: null, actorFallback: "Iván SC", result: "Éxito", criticality: "Media", hasProject: false },
  { action: "ecommerce.product_published", title: "Producto publicado", detail: "Escaparate actualizado", actorRole: "ecommerce", actorFallback: "Storefront Builder", result: "Éxito", criticality: "Baja", hasProject: true },
  { action: "marketing.campaign_created", title: "Campaña creada (borrador)", detail: "Pendiente de revisión", actorRole: "marketing", actorFallback: "Acquisition Agent", result: "Creado", criticality: "Baja", hasProject: true },
  { action: "operations.order_sent", title: "Pedido enviado al proveedor", detail: "Confirmación pendiente", actorRole: "operations", actorFallback: "Operations Agent", result: "Éxito", criticality: "Baja", hasProject: false },
  { action: "system.api_error", title: "Fallo en consulta API externa", detail: "Reintento programado", actorRole: null, actorFallback: "System", result: "Error", criticality: "Media", hasProject: false },
  { action: "auth.login", title: "Inicio de sesión", detail: "Acceso al centro de control", actorRole: null, actorFallback: "Iván SC", result: "Éxito", criticality: "Baja", hasProject: false },
  { action: "pricing.price_changed", title: "Cambio de precio", detail: "Precio de venta actualizado", actorRole: "finance", actorFallback: "Dynamic Pricing Agent", result: "Éxito", criticality: "Media", hasProject: true },
];

/** Tipo que se enseña en la tabla, por prefijo de la acción. */
export const TYPE_BY_PREFIX: Record<string, string> = {
  approval: "Aprobación",
  cfo: "Finanzas",
  marketing: "Marketing",
  legal: "Legal",
  sourcing: "Proveedor",
  config: "Configuración",
  ecommerce: "Tienda",
  marketplace: "Tienda",
  operations: "Operaciones",
  system: "Error",
  auth: "Seguridad",
  kill_switch: "Seguridad",
  pricing: "Precio",
  research: "Investigación",
  economics: "Finanzas",
  pipeline: "Pipeline",
  decision: "Decisión",
  project: "Proyecto",
  task: "Proyecto",
};

/** Dirección IP y agente de usuario del evento (el backend no los guarda). */
export const DEMO_CLIENT = { ip: "192.168.1.24", userAgent: "Mozilla/5.0 (Windows NT 11.0) AMAZONA Control Center" };

/** Evidencias asociadas a un evento. */
export const DEMO_EVIDENCES = [
  { name: "Informe económico", type: "PDF", sizeKb: 183 },
  { name: "Legal Gate", type: "PDF", sizeKb: 420 },
  { name: "Presupuesto CFO", type: "PDF", sizeKb: 210 },
  { name: "Solicitud Marketing", type: "JSON", sizeKb: 12 },
  { name: "Configuración de campaña", type: "JSON", sizeKb: 8 },
];

/** Comprobaciones de integridad del registro. */
export const INTEGRITY_CHECKS = [
  "Hash verificado",
  "Firma de integridad",
  "Evento inmutable",
  "Evidencia completa",
  "Cadena de eventos válida",
];

/** Minutos desde la última verificación de integridad. */
export const INTEGRITY_LAST_CHECK_MINUTES = 3;

/** Proporción de eventos con evidencia completa. */
export const EVIDENCE_COMPLETE_RATE = 0.994;

/** Política de retención del registro (no hay configuración en el backend). */
export const RETENTION_POLICY = [
  { key: "events", label: "Eventos de auditoría", period: "7 años", detail: "Obligación mercantil y fiscal" },
  { key: "evidence", label: "Evidencias documentales", period: "7 años", detail: "Junto al evento que las genera" },
  { key: "security", label: "Eventos de seguridad", period: "2 años", detail: "Accesos y cambios de permisos" },
  { key: "telemetry", label: "Telemetría de agentes", period: "90 días", detail: "Latencia, coste y errores" },
];

/** Anomalías detectadas en los últimos 7 días. */
export const DEMO_ANOMALIES = [
  { level: "Crítica", count: 1, text: "Precio cambiado sin aprobación" },
  { level: "Media", count: 2, text: "Cambios de configuración inusuales" },
  { level: "Baja", count: 1, text: "Actividad fuera de horario" },
];

/** Formatos del paquete de auditoría exportable. */
export const EXPORT_FORMATS = ["CSV", "JSON", "PDF firmado"];

/** Hash del evento, determinista por id. */
export function demoHash(id: string): string {
  const base = Math.floor(demoRandom(id, "hash") * 0xffffffff).toString(16).padStart(8, "0");
  const tail = Math.floor(demoRandom(id, "hash2") * 0xffffffff).toString(16).padStart(8, "0");
  return `${base}${tail}`;
}

/** Cuántas evidencias tiene un evento (0–5). */
export function demoEvidenceCount(id: string): number {
  return Math.floor(demoRandom(id, "evidence") * 6);
}
