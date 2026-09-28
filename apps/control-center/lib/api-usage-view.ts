import type { ApiProviderUsage } from "./api.ts";

// Lo que el panel Estado dice del gasto en APIs externas (Milestone 37, plan
// maestro §25). Toda la lógica vive aquí con sus tests; la tarjeta solo presenta.
//
// La regla que gobierna este fichero: **no enseñar un cero inventado**. Un coste
// que el proveedor todavía no ha comunicado es ausente, un límite que nadie ha
// autorizado es ausente, y una cuota que el proveedor no publica es ausente. Las
// tres cosas se parecen a un cero y ninguna lo es.

export type QuotaStatus = "sin-limite" | "holgado" | "ajustado" | "agotado";

export interface ApiUsageRow {
  provider: string;
  /** «Gratuito» o «De pago». Decirlo importa: lo segundo necesita autorización. */
  pricingLabel: string;
  /** `8 de 5.000 peticiones`, o `8 peticiones` si no hay cuota publicada. */
  consumption: string;
  /** 0–100 contra la cuota diaria, o `null` si no hay cuota contra la que medir.
   * `null` no es 0: es que no hay barra que dibujar. */
  quotaPercent: number | null;
  quotaStatus: QuotaStatus;
  /** Lo estimado hoy, con su moneda. */
  estimatedCost: string;
  /** Lo que el proveedor ha cobrado de verdad, o `null` si no lo ha dicho. */
  actualCost: string | null;
  /** Lo autorizado, o la frase que explica que no hay autorización. */
  authorisation: string;
  /** Llamadas denegadas hoy y el motivo de la última. */
  deniedLabel: string | null;
  source: string;
}

const PRICING_LABEL: Record<ApiProviderUsage["pricing"], string> = {
  free: "Gratuito",
  paid: "De pago",
};

const UNIT_LABEL: Record<string, string> = {
  requests: "peticiones",
  tokens: "tokens",
  credits: "créditos",
};

export function unitLabel(unit: string): string {
  return UNIT_LABEL[unit] ?? unit;
}

function amount(value: number, currency: string): string {
  return `${value.toFixed(2)} ${currency}`;
}

/** Cuánto queda de cuota, en una palabra.
 *
 * `sin-limite` cuando no hay cuota publicada: no significa «infinito», significa
 * que no sabemos contra qué medir, y por eso no se dibuja barra. */
export function quotaStatusOf(used: number, quota: number | null): QuotaStatus {
  if (quota === null || quota <= 0) return "sin-limite";
  const ratio = used / quota;
  if (ratio >= 1) return "agotado";
  if (ratio >= 0.8) return "ajustado";
  return "holgado";
}

export function buildApiUsageRows(usage: ApiProviderUsage[]): ApiUsageRow[] {
  return usage.map((row) => {
    const unit = unitLabel(row.unit);
    return {
      provider: row.provider,
      pricingLabel: PRICING_LABEL[row.pricing] ?? row.pricing,
      consumption:
        row.quota_units_per_day === null
          ? `${row.units_today} ${unit}`
          : `${row.units_today} de ${row.quota_units_per_day} ${unit}`,
      quotaPercent:
        row.quota_units_per_day === null || row.quota_units_per_day <= 0
          ? null
          : Math.min(100, Math.round((row.units_today / row.quota_units_per_day) * 100)),
      quotaStatus: quotaStatusOf(row.units_today, row.quota_units_per_day),
      estimatedCost: amount(row.estimated_cost_today, row.currency),
      actualCost:
        row.actual_cost_today === null ? null : amount(row.actual_cost_today, row.currency),
      authorisation: authorisationLabel(row),
      deniedLabel: deniedLabel(row),
      source: row.source,
    };
  });
}

/** Qué se ha autorizado gastar, dicho de forma que un cero no se confunda con
 * una ausencia.
 *
 * Un proveedor gratuito sin autorización no es un problema; uno de pago sin
 * autorización **no se llama**, y la frase lo dice. */
export function authorisationLabel(row: ApiProviderUsage): string {
  const limits: string[] = [];
  if (row.authorised_cost_per_day !== null) {
    limits.push(`${amount(row.authorised_cost_per_day, row.currency)}/día`);
  }
  if (row.authorised_cost_per_run !== null) {
    limits.push(`${amount(row.authorised_cost_per_run, row.currency)}/ejecución`);
  }
  if (limits.length > 0) return `Autorizado: ${limits.join(" · ")}`;
  if (row.pricing === "free") return "Sin gasto autorizado (no hace falta: es gratuito)";
  return "Sin gasto autorizado — no se llamará";
}

export function deniedLabel(row: ApiProviderUsage): string | null {
  if (row.denied_today === 0) return null;
  const calls = row.denied_today === 1 ? "1 llamada denegada hoy" : `${row.denied_today} llamadas denegadas hoy`;
  return row.last_denied_reason ? `${calls}: ${row.last_denied_reason}` : calls;
}

/** El resumen de la cabecera. `null` cuando no hay nada que resumir, que no es
 * lo mismo que «cero gasto». */
export function apiUsageSummary(usage: ApiProviderUsage[]): string | null {
  if (usage.length === 0) return null;
  const calls = usage.reduce((total, row) => total + row.units_today, 0);
  const denied = usage.reduce((total, row) => total + row.denied_today, 0);
  const spend = usage.reduce((total, row) => total + row.estimated_cost_today, 0);
  const currency = usage[0].currency;
  const parts = [`${calls} llamadas hoy`, `${amount(spend, currency)} estimados`];
  if (denied > 0) parts.push(`${denied} denegadas`);
  return parts.join(" · ");
}
