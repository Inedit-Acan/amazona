import type { EconomicAnalysis, Product } from "./api.ts";
import { add, parseDecimal, ZERO, type Decimal } from "./decimal.ts";
import { planned, type Planned } from "./provenance.ts";

// La zona PLAN del CFO (M45, Commit 10): lo que el modelo económico ESPERA, no lo que ha ocurrido.
//
// Sale de los análisis económicos que ya guarda el backend, y usa sus importes como TEXTO decimal
// (`contribution_margin_per_unit`, `contribution_margin_per_order`): el modelo del frontend (`economics-model.ts`)
// calcula con `number`, y aquí no se quiere ni un `float` en una cifra de dinero.
//
// El backend ya dice cuándo una proyección **no** se puede evaluar (`margin_evaluability`) y qué le falta
// (`missing_inputs`). Esta vista no rellena ese hueco: lo enseña. Y nunca se mezcla con la zona verificada ni con la
// declarada: `Planned<T>` no se puede sumar con `Verified<T>` ni con `Declared<T>` (no compila).
//
// Fuera a propósito, porque el modelo no puede demostrarlos: beneficio neto, EBITDA, impuestos, IVA/OSS, caja,
// comisiones de pasarela y conversión de divisas.

export interface PlanRow {
  productId: string;
  name: string;
  currency: string | null;
  /** Margen de contribución por unidad, exacto; `null` = el backend no pudo evaluarlo. */
  perUnit: Planned<Decimal> | null;
  perOrder: Planned<Decimal> | null;
  /** Unidades por pedido declaradas; `null` = no declarado (y entonces no hay margen por pedido). */
  unitsPerOrder: number | null;
  evaluable: boolean;
  /** Qué le faltó al backend para evaluarlo, por su nombre. */
  missing: string[];
  recommendation: EconomicAnalysis["recommendation"];
}

export interface PlanView {
  rows: PlanRow[];
  /** Suma del margen de contribución por pedido, sólo si TODAS las filas son evaluables y comparten moneda. */
  totalPerOrder: Planned<Decimal> | null;
  currency: string | null;
  /** Por qué no hay total, cuando no lo hay. */
  blockedBy: "no_analyses" | "not_evaluable" | "mixed_currencies" | null;
  evaluable: number;
  analysed: number;
}

/** La proyección de cada producto con análisis económico, y el total sólo cuando todas son evaluables. */
export function planView(products: Product[], analyses: Map<string, EconomicAnalysis>): PlanView {
  const names = new Map(products.map((product) => [product.id, product.name] as const));
  const rows: PlanRow[] = [];

  for (const [productId, analysis] of analyses) {
    const evaluable = analysis.margin_evaluability === "evaluable";
    const perUnit = analysis.contribution_margin_per_unit === null ? null : parseDecimal(analysis.contribution_margin_per_unit);
    const perOrder = analysis.contribution_margin_per_order === null ? null : parseDecimal(analysis.contribution_margin_per_order);
    rows.push({
      productId,
      name: names.get(productId) ?? productId,
      currency: analysis.currency,
      perUnit: evaluable && perUnit !== null ? planned(perUnit) : null,
      perOrder: evaluable && perOrder !== null ? planned(perOrder) : null,
      unitsPerOrder: analysis.units_per_order,
      evaluable,
      missing: analysis.missing_inputs ?? [],
      recommendation: analysis.recommendation,
    });
  }
  rows.sort((a, b) => a.name.localeCompare(b.name));

  const evaluableRows = rows.filter((row) => row.perOrder !== null);
  const currencies = [...new Set(rows.map((row) => row.currency).filter((currency): currency is string => currency !== null))];

  let blockedBy: PlanView["blockedBy"] = null;
  if (rows.length === 0) blockedBy = "no_analyses";
  else if (currencies.length > 1) blockedBy = "mixed_currencies";
  else if (evaluableRows.length !== rows.length) blockedBy = "not_evaluable";

  return {
    rows,
    totalPerOrder:
      blockedBy === null && evaluableRows.length > 0
        ? planned(evaluableRows.reduce((sum, row) => add(sum, row.perOrder!.value), ZERO))
        : null,
    currency: currencies.length === 1 ? currencies[0] : null,
    blockedBy,
    evaluable: evaluableRows.length,
    analysed: rows.length,
  };
}

export const PLAN_BLOCKED_TEXT: Record<NonNullable<PlanView["blockedBy"]>, string> = {
  no_analyses: "Ningún producto tiene análisis económico todavía.",
  not_evaluable: "Alguna proyección no se puede evaluar: el total sumaría huecos y no se calcula.",
  mixed_currencies: "Hay análisis en varias monedas: no se suman ni se convierten.",
};

export const PLAN_NOTE =
  "Proyección sobre los supuestos de cada análisis económico: no ha ocurrido. Es margen de contribución, no beneficio: " +
  "no incluye costes fijos, impuestos, IVA/OSS, caja, comisiones de pasarela ni conversión de divisas.";
