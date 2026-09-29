// Espejo del motor económico del backend (Milestone 40, ADR 0018).
//
// **El backend es la implementación canónica.** Lo que se guarda y lo que se
// enseña como resultado oficial sale siempre de él. Esto es para el simulador:
// mover un deslizador y ver el efecto al instante, sin una llamada por cada
// píxel.
//
// Que haya dos implementaciones es una decisión, no un descuido, y tiene su
// precio: pueden separarse. Por eso `economics-mirror.test.ts` compara este
// código con fixtures **capturados del backend** (`economics-parity-fixtures.json`),
// y falla el día que dejen de coincidir.
//
// ## Por qué aquí sí se usa coma flotante
//
// JavaScript no tiene decimales exactos sin una biblioteca, y este cálculo es
// de interfaz: se recalcula al mover un control y se descarta. Los tests de
// paridad comparan **a dos decimales**, que es lo que la pantalla enseña. Lo
// que se persiste no pasa por aquí.

import type { CostStatus } from "./api.ts";

/** Un coste del simulador, con la misma semántica de cinco estados que el
 * backend: lo que no está `known` **no suma**, y no por eso vale cero. */
export interface MirrorCost {
  status: CostStatus;
  amount: number | null;
}

export interface MirrorInputs {
  salePrice: number;
  costs: MirrorCost[];
  /** `null` = no declarado. Sin esto no hay margen por pedido ni techo de CAC. */
  unitsPerOrder: number | null;
  /** `null` = no declarado. */
  expectedMonthlyOrders: number | null;
  monthlyFixedCosts: number | null;
}

export interface MirrorResult {
  marginPerUnit: number;
  marginPercent: number;
  /** `null` cuando no se declararon las unidades por pedido. */
  marginPerOrder: number | null;
  breakevenCacBeforeFixedCosts: number | null;
  allocatedFixedCostPerOrder: number | null;
  maxBreakevenCac: number | null;
  /** Lo que falta para que cada cifra exista, por su nombre. */
  missingInputs: string[];
}

/** Solo los costes conocidos entran en la suma — igual que en el backend, y por
 * el mismo motivo: un coste incluido en otro se contaría dos veces y uno que no
 * aplica no es un coste de cero. */
export function totalCost(costs: MirrorCost[]): number {
  return costs
    .filter((c) => c.status === "known" && c.amount !== null)
    .reduce((sum, c) => sum + (c.amount ?? 0), 0);
}

/** La cadena unidad → pedido → adquisición. Misma fórmula que
 * `app/economics/unit_economics.py`. */
export function evaluateMirror(inputs: MirrorInputs): MirrorResult {
  const missingInputs: string[] = [];
  const marginPerUnit = inputs.salePrice - totalCost(inputs.costs);
  const marginPercent = inputs.salePrice > 0 ? marginPerUnit / inputs.salePrice : 0;

  let marginPerOrder: number | null = null;
  if (inputs.unitsPerOrder === null) {
    // Un 1 que nadie ha declarado no vale: es la suposición que el Milestone 40
    // quita de en medio.
    missingInputs.push("units_per_order");
  } else {
    marginPerOrder = marginPerUnit * inputs.unitsPerOrder;
  }

  if (inputs.expectedMonthlyOrders === null) missingInputs.push("expected_monthly_orders");
  if (inputs.monthlyFixedCosts === null) missingInputs.push("monthly_fixed_costs");

  const allocatedFixedCostPerOrder =
    inputs.expectedMonthlyOrders !== null &&
    inputs.expectedMonthlyOrders > 0 &&
    inputs.monthlyFixedCosts !== null
      ? inputs.monthlyFixedCosts / inputs.expectedMonthlyOrders
      : null;

  const maxBreakevenCac =
    marginPerOrder !== null && allocatedFixedCostPerOrder !== null
      ? marginPerOrder - allocatedFixedCostPerOrder
      : null;

  return {
    marginPerUnit,
    marginPercent,
    marginPerOrder,
    breakevenCacBeforeFixedCosts: marginPerOrder,
    allocatedFixedCostPerOrder,
    maxBreakevenCac,
    missingInputs,
  };
}
