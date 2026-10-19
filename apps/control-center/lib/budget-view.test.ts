import assert from "node:assert/strict";
import { test } from "node:test";
import type { BudgetFigures, BudgetRead } from "./api.ts";
import {
  BUDGET_EMPTY_LABEL,
  BUDGET_EXHAUSTED_LABEL,
  budgetView,
  readBudget,
  type BudgetLoadedView,
  type BudgetView,
} from "./budget-view.ts";
import { READ_UNAVAILABLE_VALUE, READ_UNREAD_TEXT, unreadState } from "./read-state.ts";

// El presupuesto operativo en pantalla (M47). Lo que estas pruebas fijan: todo sale de lo que el backend lee (nada hardcodeado: ni
// 1,00 ni EUR), «no hay presupuesto» es un hecho y no un error, un error NO es un cero ni «Agotado», lo disponible es
// techo − reservado − comprometido (sin restar lo gastado, que ya está dentro de lo comprometido), y una contabilidad que no
// cuadra se ve como inconsistencia en vez de pintarse como un porcentaje falso.

const budget = (over: Partial<BudgetFigures> = {}): BudgetFigures => ({
  name: "orchestrator-default",
  period: "monthly",
  currency: "EUR",
  currency_source: "accounting_currency",
  hard_limit: "100.00",
  soft_limit: null,
  reserved: "0.00",
  committed: "0.00",
  spent: "0.00",
  remaining: "100.00",
  ...over,
});

const reading = (value: BudgetFigures | null, over: Partial<BudgetRead> = {}): BudgetRead => ({
  authorised: value !== null,
  budget: value,
  read_at: "2026-10-19T12:05:00.123456Z",
  ...over,
});

async function view(value: BudgetFigures | null, over: Partial<BudgetRead> = {}): Promise<BudgetView> {
  return readBudget({ getBudget: async () => reading(value, over) });
}

async function loaded(value: BudgetFigures): Promise<BudgetLoadedView> {
  const result = await view(value);
  assert.equal(result.kind, "loaded", JSON.stringify(result));
  return result as BudgetLoadedView;
}

class StatusError extends Error {
  status: number;

  constructor(status: number) {
    super(`HTTP ${status}`);
    this.status = status;
  }
}

// --- A · no hay presupuesto ---------------------------------------------------------------------------------------------

test("A · sin presupuesto autorizado: «No hay presupuesto autorizado», que es un hecho (vacío) y no un error ni un cero", async () => {
  const result = await view(null);
  assert.equal(result.kind, "empty");
  assert.equal((result as { label: string }).label, BUDGET_EMPTY_LABEL);
  assert.equal(BUDGET_EMPTY_LABEL, "No hay presupuesto autorizado");
  assert.doesNotMatch(JSON.stringify(result), /\b0[,.]00\b|Agotado|No disponible/);
});

// --- B · C · D · E · disponible, reservado, comprometido, agotado ------------------------------------------------------

test("B · techo 100, nada movido: disponible 100", async () => {
  const result = await loaded(budget());
  assert.equal(result.status, "available");
  assert.equal(result.statusLabel, "Disponible");
  assert.deepEqual(
    [result.hardLimit, result.reserved, result.committed, result.spent, result.remaining],
    ["100,00 €", "0,00 €", "0,00 €", "0,00 €", "100,00 €"],
  );
  assert.equal(result.usedPercent, 0);
});

test("C · techo 100, reservado 25: disponible 75, parcialmente usado, y lo reservado se ve aparte", async () => {
  const result = await loaded(budget({ reserved: "25.00", remaining: "75.00" }));
  assert.equal(result.status, "partial");
  assert.equal(result.statusLabel, "Parcialmente usado");
  assert.deepEqual([result.reserved, result.committed, result.remaining], ["25,00 €", "0,00 €", "75,00 €"]);
  assert.equal(result.usedPercent, 25);
  assert.deepEqual(result.bar, { reservedPercent: 25, committedPercent: 0 });
});

test("D · techo 100, comprometido 40 (y gastado 40): disponible 60, y lo gastado NO se resta otra vez (no son 80)", async () => {
  const result = await loaded(budget({ committed: "40.00", spent: "40.00", remaining: "60.00" }));
  assert.equal(result.status, "partial");
  assert.deepEqual([result.committed, result.spent, result.remaining], ["40,00 €", "40,00 €", "60,00 €"]);
  assert.equal(result.usedPercent, 40);
  assert.deepEqual(result.bar, { reservedPercent: 0, committedPercent: 40 });
});

test("D2 · reservado y comprometido a la vez se enseñan por separado y suman en lo usado", async () => {
  const result = await loaded(budget({ reserved: "25.00", committed: "40.00", spent: "40.00", remaining: "35.00" }));
  assert.equal(result.usedPercent, 65);
  assert.deepEqual(result.bar, { reservedPercent: 25, committedPercent: 40 });
  assert.equal(result.remaining, "35,00 €");
});

test("E · agotado: disponible 0 con techo > 0 ⇒ «Agotado», tanto si es comprometido como si está reservado", async () => {
  const committed = await loaded(budget({ committed: "100.00", spent: "100.00", remaining: "0.00" }));
  assert.equal(committed.status, "exhausted");
  assert.equal(committed.statusLabel, BUDGET_EXHAUSTED_LABEL);
  assert.equal(BUDGET_EXHAUSTED_LABEL, "Agotado");
  assert.equal(committed.remaining, "0,00 €");
  const reserved = await loaded(budget({ reserved: "100.00", remaining: "0.00" }));
  assert.equal(reserved.status, "exhausted");
  assert.equal(reserved.usedPercent, 100);
});

// --- F · G · error y sin leer --------------------------------------------------------------------------------------------

test("F · una lectura que falla es «No disponible»: ni 0, ni 0,00 €, ni «Agotado», ni «No hay presupuesto»", async () => {
  for (const status of [401, 403, 404, 500, 503, undefined]) {
    const result = await readBudget({
      getBudget: async () => {
        throw status === undefined ? new Error("fetch failed ECONNREFUSED") : new StatusError(status);
      },
    });
    assert.equal(result.kind, "error", String(status));
    const message = (result as { message: string }).message;
    if (status !== 401) assert.match(message, /presupuesto/i);
    assert.doesNotMatch(message, /ECONNREFUSED|fetch failed|HTTP \d+|\b[45]\d\d\b/, "el error no enseña nada técnico");
    assert.doesNotMatch(JSON.stringify(result), /\b0[,.]00\b|Agotado|No hay presupuesto autorizado|loaded|empty/);
  }
  assert.equal(READ_UNAVAILABLE_VALUE, "No disponible");
});

test("F2 · un error de permiso se dice con su causa, sin confundirse con «no hay presupuesto»", async () => {
  const denied = await readBudget({
    getBudget: async () => {
      throw new StatusError(403);
    },
  });
  assert.match((denied as { message: string }).message, /permiso/);
});

test("G · sin leer (no se intentó): «Sin leer», nunca un 0 ni un vacío", () => {
  const result = budgetView(unreadState("El presupuesto todavía no se ha leído."));
  assert.equal(result.kind, "unread");
  assert.equal((result as { reason: string }).reason, "El presupuesto todavía no se ha leído.");
  assert.equal(READ_UNREAD_TEXT, "Sin leer");
  assert.doesNotMatch(JSON.stringify(result), /\b0[,.]00\b|Agotado|No hay presupuesto/);
});

test("un ReadState vacío (el backend dijo que no hay nada) es «No hay presupuesto autorizado», no un error", () => {
  const result = budgetView({ kind: "empty" });
  assert.equal(result.kind, "empty");
  assert.equal((result as { label: string }).label, BUDGET_EMPTY_LABEL);
});

test("un techo cero no es un presupuesto agotado: es un contrato roto (y no divide por cero)", async () => {
  const result = await view(budget({ hard_limit: "0.00", reserved: "0.00", committed: "0.00", spent: "0.00", remaining: "0.00" }));
  assert.equal(result.kind, "error");
  assert.doesNotMatch(JSON.stringify(result), /Agotado/);
});

test("el estado «agotado» solo existe en una lectura válida con presupuesto: ningún otro estado lleva etiqueta de estado", async () => {
  const states: BudgetView[] = [
    await view(null),
    budgetView(unreadState("x")),
    await readBudget({
      getBudget: async () => {
        throw new StatusError(500);
      },
    }),
  ];
  for (const state of states) {
    assert.ok(!("statusLabel" in state), state.kind);
    assert.ok(!("remaining" in state), state.kind);
  }
});

// --- H · la moneda -------------------------------------------------------------------------------------------------------

test("H · sin moneda: no se inventa EUR. Los importes salen sin símbolo y se dice que la moneda no está disponible", async () => {
  const withoutCurrency: Partial<BudgetFigures> = budget({ committed: "40.00", spent: "40.00", remaining: "60.00" });
  delete withoutCurrency.currency;
  const result = await loaded(withoutCurrency as BudgetFigures);
  assert.equal(result.currency, null);
  assert.equal(result.currencyNote, "Moneda no disponible");
  assert.deepEqual([result.hardLimit, result.committed, result.remaining], ["100,00", "40,00", "60,00"]);
  assert.doesNotMatch(JSON.stringify(result), /€|EUR/);
});

test("H2 · una moneda sin su procedencia contractual tampoco se da por buena", async () => {
  for (const over of [{ currency_source: undefined }, { currency_source: "guess" }, { currency: "euro" }, { currency: "" }, { currency: null }]) {
    const result = await loaded(budget(over as unknown as Partial<BudgetFigures>));
    assert.equal(result.currency, null, JSON.stringify(over));
    assert.doesNotMatch(JSON.stringify(result), /€|EUR/, JSON.stringify(over));
  }
});

test("H3 · con moneda y procedencia, se enseña la que dice el backend (no «EUR» por defecto)", async () => {
  const result = await loaded(budget({ currency: "USD" }));
  assert.equal(result.currency, "USD");
  assert.equal(result.hardLimit, "100,00 USD");
  assert.equal(result.currencyNote, null);
});

// --- I · contrato roto ---------------------------------------------------------------------------------------------------

test("I · sin techo, o con un contrato roto, es un ERROR visible (no un presupuesto a cero ni «no hay presupuesto»)", async () => {
  const broken: unknown[] = [
    { hard_limit: undefined },
    { hard_limit: null },
    { hard_limit: "" },
    { hard_limit: "abc" },
    { hard_limit: "0.00" },
    { hard_limit: "-5.00", remaining: "-5.00" },
    { reserved: undefined },
    { committed: undefined },
    { spent: undefined },
    { remaining: undefined },
    { reserved: "-1.00", remaining: "101.00" },
    { committed: "NaN" },
    { soft_limit: "xx" },
    { hard_limit: 100 },
  ];
  for (const over of broken) {
    const result = await view(budget(over as Partial<BudgetFigures>));
    assert.equal(result.kind, "error", JSON.stringify(over));
    assert.doesNotMatch(JSON.stringify(result), /Agotado|No hay presupuesto autorizado/, JSON.stringify(over));
  }
});

test("I2 · la respuesta entera rota (sin `authorised`, sin objeto, o contradictoria) es un error", async () => {
  for (const raw of [null, undefined, "x", 7, {}, { authorised: "yes", budget: null }, { authorised: true, budget: null }, { authorised: false, budget: budget() }]) {
    const result = await readBudget({ getBudget: async () => raw as unknown as BudgetRead });
    assert.equal(result.kind, "error", JSON.stringify(raw));
  }
});

test("I3 · un «disponible» que no cuadra con techo − reservado − comprometido es un contrato roto, no un dato", async () => {
  const result = await view(budget({ reserved: "25.00", remaining: "99.00" }));
  assert.equal(result.kind, "error");
  assert.match((result as { message: string }).message, /cuadra|contrato/i);
});

test("I4 · lo gastado no se resta de lo disponible: un `remaining` que sí lo resta es un contrato roto", async () => {
  const result = await view(budget({ committed: "40.00", spent: "40.00", remaining: "20.00" }));
  assert.equal(result.kind, "error");
});

// --- J · K · inconsistencia ----------------------------------------------------------------------------------------------

test("J · comprometido > techo: inconsistencia visible, sin porcentaje ni barra falsos", async () => {
  const result = await loaded(budget({ committed: "130.00", spent: "130.00", remaining: "-30.00" }));
  assert.equal(result.status, "inconsistent");
  assert.equal(result.statusLabel, "Inconsistente");
  assert.equal(result.usedPercent, null);
  assert.equal(result.bar, null);
  assert.match(result.inconsistency ?? "", /supera el techo/);
  assert.equal(result.remaining, "−30,00 €", "lo disponible negativo se ve, no se recorta a cero");
});

test("K · reservado + comprometido > techo: inconsistencia visible aunque ninguno la supere por separado", async () => {
  const result = await loaded(budget({ reserved: "60.00", committed: "60.00", spent: "60.00", remaining: "-20.00" }));
  assert.equal(result.status, "inconsistent");
  assert.equal(result.usedPercent, null);
  assert.equal(result.bar, null);
  assert.notEqual(result.statusLabel, "Agotado");
});

test("una inconsistencia nunca se presenta como «Agotado» ni como «Disponible»", async () => {
  const result = await loaded(budget({ reserved: "100.01", remaining: "-0.01" }));
  assert.equal(result.status, "inconsistent");
});

// --- L · el presupuesto actual de Supabase -------------------------------------------------------------------------------

test("L · el presupuesto real tras la segunda misión: 1,00 / 0 / 1 / 1 / 0 ⇒ agotado, leído de los datos", async () => {
  const result = await loaded(budget({ hard_limit: "1.00", reserved: "0.00", committed: "1.00", spent: "1.00", remaining: "0.00" }));
  assert.equal(result.status, "exhausted");
  assert.deepEqual(
    [result.hardLimit, result.reserved, result.committed, result.spent, result.remaining],
    ["1,00 €", "0,00 €", "1,00 €", "1,00 €", "0,00 €"],
  );
  assert.equal(result.usedPercent, 100);
});

// --- Nada hardcodeado ----------------------------------------------------------------------------------------------------

test("no depende del valor de la prueba: con cualquier techo se enseña ese techo", async () => {
  for (const hard of ["2.00", "10.00", "500.00", "1234567.89"]) {
    const result = await loaded(budget({ hard_limit: hard, remaining: hard }));
    const expected = hard === "1234567.89" ? "1.234.567,89 €" : `${hard.replace(".", ",")} €`;
    assert.equal(result.hardLimit, expected);
    assert.equal(result.remaining, expected);
    assert.equal(result.status, "available");
  }
});

test("el porcentaje usado es exacto (aritmética entera) y no redondea hacia arriba un casi agotado", async () => {
  const third = await loaded(budget({ hard_limit: "3.00", committed: "1.00", spent: "1.00", remaining: "2.00" }));
  assert.equal(third.usedPercent, 33.3);
  const almost = await loaded(budget({ hard_limit: "100.00", committed: "99.99", spent: "99.99", remaining: "0.01" }));
  assert.equal(almost.status, "partial", "con un céntimo disponible no es «Agotado»");
  assert.equal(almost.usedPercent, 99.9, "99,99 % no se enseña como 100 %");
});

// --- periodo, umbral y hora de lectura -----------------------------------------------------------------------------------

test("el periodo se enseña como lo declara la fila, y si falta se dice", async () => {
  assert.equal((await loaded(budget({ period: "monthly" }))).period, "Mensual");
  assert.equal((await loaded(budget({ period: "weekly" }))).period, "weekly");
  const withoutPeriod: Partial<BudgetFigures> = budget();
  delete withoutPeriod.period;
  assert.equal((await loaded(withoutPeriod as BudgetFigures)).period, "No disponible");
});

test("el umbral de aviso se enseña cuando existe y no se inventa cuando no", async () => {
  assert.equal((await loaded(budget({ soft_limit: "80.00" }))).softLimit, "80,00 €");
  assert.equal((await loaded(budget())).softLimit, null);
});

test("la hora de lectura es la del backend, en UTC; si no es válida, no se escribe ninguna", async () => {
  assert.equal((await loaded(budget())).readAt, "19 oct 2026 · 12:05 UTC");
  const bad = await view(budget(), { read_at: "ayer" });
  assert.equal((bad as BudgetLoadedView).readAt, null);
  const missing = await view(budget(), { read_at: undefined as unknown as string });
  assert.equal((missing as BudgetLoadedView).readAt, null);
});

test("la fuente es una sola lectura por petición", async () => {
  let calls = 0;
  await readBudget({
    getBudget: async () => {
      calls += 1;
      return reading(budget());
    },
  });
  assert.equal(calls, 1);
});

test("la vista dice de dónde sale y que no es caja ni ingresos", async () => {
  const result = await loaded(budget());
  assert.match(result.sourceNote, /presupuesto autorizado/i);
  assert.match(result.scopeNote, /no es (caja|cash)/i);
  assert.match(result.scopeNote, /ingresos/i);
});
