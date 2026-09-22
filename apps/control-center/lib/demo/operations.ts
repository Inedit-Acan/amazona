// DATOS DE DEMOSTRACIÓN — pantalla de Operaciones.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona: AMAZONA
// no recibe pedidos reales, no hay clientes, transportistas, incidencias ni
// devoluciones, así que todo el Control Tower es simulado. Deterministas por
// pedido (demoRandom). Lo real —productos, cotizaciones de proveedor, precio y
// el informe del agente de operaciones— se usa siempre que existe. Sustituir
// cuando existan los endpoints (docs/design/AMAZONA_estado_paneles_rediseno.md,
// sección 6).

import { demoRandom } from "./random.ts";

/** Pedidos que entran cada día en la ventana de demostración. */
export const ORDERS_PER_DAY = 12;

export const PERIODS = [
  { value: "today", label: "Hoy", days: 1 },
  { value: "7d", label: "Últimos 7 días", days: 7 },
  { value: "30d", label: "Últimos 30 días", days: 30 },
] as const;

export type PeriodValue = (typeof PERIODS)[number]["value"];

/** Ventana completa que se genera (la mayor de PERIODS). */
export const WINDOW_DAYS = 30;

export const DEMO_CHANNELS = ["Web", "Amazon", "TikTok", "Instagram"];

/** Clientes de ejemplo (iniciales + apellido, como en el mockup). */
export const DEMO_CUSTOMERS = [
  "M. García",
  "L. Fernández",
  "A. Torres",
  "C. López",
  "J. Martínez",
  "S. Ruiz",
  "P. Navarro",
  "N. Castro",
  "R. Iglesias",
  "V. Moreno",
  "D. Sanz",
  "E. Ortega",
];

export interface DemoCarrier {
  name: string;
  /** Entregas a tiempo (0–1) y días medios de entrega. */
  onTime: number;
  avgDays: number;
  /** Regiones de origen que sirve este transportista. */
  regions: string[];
}

export const DEMO_CARRIERS: DemoCarrier[] = [
  { name: "DHL", onTime: 0.964, avgDays: 2.8, regions: ["eu", "china", "vietnam"] },
  { name: "Correos Express", onTime: 0.941, avgDays: 2.4, regions: ["eu"] },
  { name: "UPS", onTime: 0.972, avgDays: 2.7, regions: ["eu", "mexico"] },
  { name: "Cainiao", onTime: 0.838, avgDays: 7.1, regions: ["china", "vietnam"] },
  { name: "DHL eCommerce", onTime: 0.913, avgDays: 4.2, regions: ["china", "eu", "mexico"] },
];

/** Días de tránsito típicos desde la región del proveedor al mercado de destino. */
export const DEMO_TRANSIT_DAYS: Record<string, number> = {
  eu: 3,
  china: 9,
  vietnam: 11,
  mexico: 5,
};

/** Mercados de destino y su peso en los pedidos. */
export const DEMO_MARKETS = [
  { value: "eu", label: "España + UE", weight: 0.62, lonLat: [-3.7, 40.4] as [number, number] },
  { value: "us", label: "Estados Unidos", weight: 0.26, lonLat: [-98.5, 39.8] as [number, number] },
  { value: "mx", label: "México", weight: 0.12, lonLat: [-102.5, 23.6] as [number, number] },
];

export type IncidentKind = "supplier_unconfirmed" | "tracking_stalled" | "customs_hold" | "address_change" | "damaged";

export interface DemoIncidentType {
  kind: IncidentKind;
  severity: "Crítica" | "Alta" | "Media";
  title: string;
  /** Texto de apoyo: {carrier} y {origin} se sustituyen por los del pedido. */
  detail: string;
  action: string;
  /** Horas que lleva abierta (aproximadas). */
  hours: number;
}

export const DEMO_INCIDENT_TYPES: DemoIncidentType[] = [
  { kind: "supplier_unconfirmed", severity: "Crítica", title: "Proveedor no confirma pedido", detail: "SLA excedido: +{hours} h", action: "Resolver", hours: 4 },
  { kind: "tracking_stalled", severity: "Alta", title: "Tracking sin movimiento 72 h", detail: "Transportista: {carrier}", action: "Investigar", hours: 72 },
  { kind: "customs_hold", severity: "Alta", title: "Retención aduanera", detail: "{origin} → destino", action: "Ver detalles", hours: 26 },
  { kind: "address_change", severity: "Media", title: "Cliente solicita cambio de dirección", detail: "Antes del despacho", action: "Gestionar", hours: 6 },
  { kind: "damaged", severity: "Media", title: "Producto dañado en tránsito", detail: "Transportista: {carrier}", action: "Gestionar", hours: 12 },
];

/** Proporción de pedidos con incidencia abierta. */
export const DEMO_INCIDENT_RATE = 0.1;

/** Proporción de pedidos entregados que acaban devueltos. */
export const DEMO_RETURN_RATE = 0.038;

export const DEMO_RETURN_REASONS = [
  { label: "Producto defectuoso", share: 0.31 },
  { label: "No cumple expectativas", share: 0.24 },
  { label: "Talla / compatibilidad", share: 0.18 },
  { label: "Entrega tardía", share: 0.14 },
  { label: "Otros", share: 0.13 },
];

/** Objetivo de tasa de devolución del panel. */
export const DEMO_RETURN_TARGET = 0.05;

/** Reparto de las devoluciones por estado. */
export const DEMO_RETURN_STATES = [
  { key: "open", label: "Abiertas", share: 0.5 },
  { key: "review", label: "Revisión", share: 0.125 },
  { key: "transit", label: "En tránsito", share: 0.25 },
  { key: "received", label: "Recibidas", share: 0.125 },
];

/** Defectos declarados por proveedor (el backend solo da fiabilidad). */
export const DEMO_DEFECT_RANGE = { min: 0.003, max: 0.02 };

export interface DemoAutomation {
  key: string;
  label: string;
  detail: string;
  /** Modos operativos en los que la regla está activa. */
  activeIn: OperatingMode[];
}

export type OperatingMode = "manual" | "semi" | "auto";

export const OPERATING_MODES: { value: OperatingMode; label: string; detail: string }[] = [
  { value: "manual", label: "Manual", detail: "Cada paso lo confirma una persona." },
  { value: "semi", label: "Semi-automático", detail: "Las rutinas se ejecutan solas; lo excepcional se escala." },
  { value: "auto", label: "Automático", detail: "Todo se ejecuta solo; solo se avisa de los bloqueos." },
];

export const DEMO_AUTOMATIONS: DemoAutomation[] = [
  { key: "order-to-supplier", label: "Pedido → Proveedor", detail: "Al cobrar, el pedido se envía al proveedor.", activeIn: ["semi", "auto"] },
  { key: "tracking", label: "Seguimiento tracking", detail: "Comprueba el tracking cada 6 h.", activeIn: ["manual", "semi", "auto"] },
  { key: "delay-alert", label: "Aviso retrasos", detail: "Alerta si el pedido supera el SLA.", activeIn: ["manual", "semi", "auto"] },
  { key: "customer-notice", label: "Notificación cliente", detail: "Avisa al cliente en cada hito del envío.", activeIn: ["semi", "auto"] },
  { key: "incident-escalation", label: "Escalado incidencias", detail: "Escala a una persona lo que la IA no resuelve.", activeIn: ["auto"] },
];

/** Variación de un KPI frente al periodo anterior (fracción, determinista). */
export function demoKpiDelta(key: string, max: number): number {
  return Math.round((demoRandom(key, "kpi-delta") * 2 - 1) * max * 1000) / 1000;
}

/** Segundos desde la última sincronización con proveedores y transportistas. */
export const DEMO_SYNC_SECONDS = 18;
