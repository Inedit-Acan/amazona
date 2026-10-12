import type { RevenueEntriesPage, RevenueSeries, RevenueSummary } from "./api.ts";
import { isOrigin, ORIGINS } from "./provenance.ts";

// El contrato de procedencia de los ingresos (M46, Commit 3, ADR 0031). Aquí NO se calcula nada: se comprueba que lo
// que llegó es el contrato nuevo, y si no lo es, se FALLA con un error legible en vez de enseñar otra cosa.
//
// Antes, `GET /api/revenue/summary` devolvía un `consolidated_eur` que sumaba todos los orígenes (mock, sandbox, real).
// Ya no existe: cada cifra va por origen. Un lector que siguiera pidiendo ese campo vería «Sin datos» aunque hubiera
// datos; en cambio un backend antiguo (o uno cuya respuesta perdió el origen) se rechaza aquí, a la vista, y un origen
// ausente o desconocido NUNCA se convierte en `mock`, `sandbox` ni `real` (ADR 0031 §9).

/** El vocabulario cerrado de orígenes: el de `lib/provenance.ts`, la única fuente. */
export const PROVIDER_KINDS = ORIGINS;

export class RevenueContractError extends Error {
  constructor(message: string) {
    super(`El contrato de ingresos cambió: ${message}`);
    this.name = "RevenueContractError";
  }
}

function checkOrigin(value: unknown, where: string): void {
  if (!isOrigin(value)) {
    throw new RevenueContractError(`${where} no trae un provider_kind válido (${ORIGINS.join(", ")}), trae ${JSON.stringify(value)}`);
  }
}

function checkRows(rows: unknown, where: string): void {
  if (!Array.isArray(rows)) throw new RevenueContractError(`${where} no es una lista`);
  rows.forEach((row, index) => checkOrigin((row as { provider_kind?: unknown })?.provider_kind, `${where}[${index}]`));
}

export function assertRevenueSummary(summary: RevenueSummary): RevenueSummary {
  if ("consolidated_eur" in (summary as unknown as Record<string, unknown>)) {
    throw new RevenueContractError(
      "la respuesta trae consolidated_eur, que sumaba todos los orígenes; ahora es consolidated_eur_by_origin",
    );
  }
  checkRows(summary.consolidated_eur_by_origin, "consolidated_eur_by_origin");
  checkRows(summary.entries_by_provider_kind, "entries_by_provider_kind");
  checkRows(summary.verified, "verified");
  checkRows(summary.under_review, "under_review");
  checkRows(summary.pending_evidence?.by_currency, "pending_evidence.by_currency");
  return summary;
}

export function assertRevenueSeries(series: RevenueSeries): RevenueSeries {
  checkRows(series.buckets, "buckets");
  return series;
}

export function assertRevenueEntries(page: RevenueEntriesPage): RevenueEntriesPage {
  checkRows(page.items, "items");
  return page;
}
