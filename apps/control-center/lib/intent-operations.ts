/** Las operaciones que el backend exige idempotentes, y el nombre con el que el frontend las identifica en una intención
 * (Milestone 44, ADR 0025 y 0028 §9).
 *
 * Es el reflejo, en el cliente, de las rutas `GENERIC` y `EXTERNAL_WRITE` de
 * `backend/tests/unit/test_post_route_classification.py`: cada una exige `Idempotency-Key` (428 si falta) y repetirla con la
 * misma clave no repite su efecto. `intent-operations.test.ts` compara las dos listas: una ruta nueva con clave en el
 * backend que el cliente no conoce hace fallar la prueba, y es el momento de decidir cómo la conserva la interfaz.
 *
 * El nombre de la operación forma la *ranura* de una intención junto con el objetivo (`lib/intent-key.ts`): es un
 * identificador estable, no un texto para el usuario. */

export const OPERATIONS = {
  orderCreate: "order.create",
  orderPayment: "order.payment",
  orderRefund: "order.refund",
  orderFulfillment: "order.fulfillment",
  fulfillmentPurchase: "fulfillment.purchase",
  fulfillmentShip: "fulfillment.ship",
  objectiveRun: "objective.run",
  legalRun: "legal.run",
  researchRun: "research.run",
  researchComparison: "research.comparison",
  regulatoryVerify: "regulatory.verify",
  transpositionVerify: "transposition.verify",
  exchangeRatesRefresh: "exchange-rates.refresh",
  exchangeRatesBackfill: "exchange-rates.backfill",
} as const;

export type OperationName = (typeof OPERATIONS)[keyof typeof OPERATIONS];

export interface KeyedOperation {
  operation: OperationName;
  /** La ruta tal como la declara el backend. Siempre `POST`. */
  path: string;
  /** `external`: pasa por `ExternalAction` y el ActionGate además de la clave. `generic`: solo la idempotencia genérica. */
  kind: "generic" | "external";
  /** `true` cuando una pantalla de hoy la lanza y por tanto usa una clave de intención. */
  inInterface: boolean;
}

export const KEYED_OPERATIONS: readonly KeyedOperation[] = [
  { operation: OPERATIONS.orderCreate, path: "/api/orders", kind: "generic", inInterface: false },
  { operation: OPERATIONS.orderPayment, path: "/api/orders/{order_id}/payments", kind: "external", inInterface: false },
  { operation: OPERATIONS.orderRefund, path: "/api/orders/{order_id}/refunds", kind: "external", inInterface: false },
  { operation: OPERATIONS.orderFulfillment, path: "/api/orders/{order_id}/fulfillments", kind: "generic", inInterface: false },
  {
    operation: OPERATIONS.fulfillmentPurchase,
    path: "/api/fulfillments/{fulfillment_id}/purchase",
    kind: "external",
    inInterface: false,
  },
  { operation: OPERATIONS.fulfillmentShip, path: "/api/fulfillments/{fulfillment_id}/ship", kind: "external", inInterface: false },
  { operation: OPERATIONS.objectiveRun, path: "/api/objectives/{objective_id}/run", kind: "generic", inInterface: true },
  { operation: OPERATIONS.legalRun, path: "/api/legal/runs", kind: "generic", inInterface: true },
  { operation: OPERATIONS.researchRun, path: "/api/research/runs", kind: "generic", inInterface: true },
  { operation: OPERATIONS.researchComparison, path: "/api/research/comparisons", kind: "generic", inInterface: false },
  {
    operation: OPERATIONS.regulatoryVerify,
    path: "/api/regulatory-requirements/{requirement_id}/verify",
    kind: "generic",
    inInterface: true,
  },
  {
    operation: OPERATIONS.transpositionVerify,
    path: "/api/national-transpositions/{transposition_id}/verify",
    kind: "generic",
    inInterface: true,
  },
  { operation: OPERATIONS.exchangeRatesRefresh, path: "/api/exchange-rates/refresh", kind: "generic", inInterface: false },
  { operation: OPERATIONS.exchangeRatesBackfill, path: "/api/exchange-rates/backfill", kind: "generic", inInterface: false },
];
