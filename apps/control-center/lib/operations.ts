import type { OperationsRecord, TrackingStage } from "./api.ts";

// El informe de operaciones es UN pedido de muestra simulado con su seguimiento,
// la política de devoluciones y un ticket de soporte de ejemplo (operations.py).
// No hay pedidos, incidencias ni transportistas reales. Este módulo solo etiqueta
// y reexpresa lo que el agente devolvió.

export const STAGE_LABELS: Record<string, string> = {
  order_placed: "Pedido realizado",
  processing: "Proveedor procesa el pedido",
  shipped: "Despachado por el proveedor",
  out_for_delivery: "En reparto",
  delivered: "Entregado",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ");
}

export interface StageDurations {
  /** Días entre el pedido y que el proveedor lo procesa. */
  processing: number | null;
  /** Días desde que se procesa hasta que se despacha. */
  toShip: number | null;
  /** Días de tránsito, del despacho a la entrega. */
  transit: number | null;
  /** Días totales desde el pedido hasta la entrega. */
  total: number | null;
}

/** Diferencias entre las etapas del seguimiento simulado (los días son relativos al pedido). */
export function stageDurations(stages: TrackingStage[]): StageDurations {
  const offset = (name: string) => stages.find((s) => s.stage === name)?.day_offset;
  const placed = offset("order_placed");
  const processing = offset("processing");
  const shipped = offset("shipped");
  const delivered = offset("delivered");
  const diff = (a: number | undefined, b: number | undefined) => (a === undefined || b === undefined ? null : b - a);
  return {
    processing: diff(placed, processing),
    toShip: diff(processing, shipped),
    transit: diff(shipped, delivered),
    total: diff(placed, delivered),
  };
}

export const TICKET_TYPE_LABELS: Record<string, string> = {
  compliance_question: "Consulta de cumplimiento",
  order_status_inquiry: "Consulta de estado del pedido",
};

export function ticketTypeLabel(type: string): string {
  return TICKET_TYPE_LABELS[type] ?? type.replace(/_/g, " ");
}

export interface OperationsVerdict {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estado del informe traducido desde `operations_status` del agente. */
export const OPERATIONS_VERDICT: Record<OperationsRecord["operations_status"], OperationsVerdict> = {
  READY: {
    title: "Simulación lista para revisión",
    detail:
      "Economía y legal no bloquean. Es un pedido de muestra simulado: no hay pedidos, clientes ni transportistas reales.",
    tone: "ok",
  },
  NEEDS_REVIEW: {
    title: "Requiere revisión",
    detail: "Falta algún análisis previo o alguno pide revisión humana antes de operar.",
    tone: "warn",
  },
  BLOCKED: {
    title: "Bloqueada",
    detail: "El análisis económico o el legal recomiendan no continuar.",
    tone: "bad",
  },
};
