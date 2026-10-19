import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { BudgetFigures, BudgetRead, CFOReport } from "./api.ts";
import { budgetView, readBudget, type BudgetLoadedView } from "./budget-view.ts";
import { verdictView, type VerdictView } from "./cfo-verdict.ts";
import { unreadState } from "./read-state.ts";

// El veredicto del agente CFO y el presupuesto vivo no pueden contradecirse (M47). El informe del agente es una FOTO de cuando se
// emitió (hoy, de septiembre, sin presupuesto); el presupuesto operativo es el estado de ahora (`GET /api/budget`). Mezclarlos fue lo que
// dejó a `/cfo` diciendo «el presupuesto no está cerca de su límite» justo debajo de «Agotado · Usado 100 %».
//
// La regla (opción A): el veredicto NO afirma nada del presupuesto. Habla de lo que sí mira (los análisis del catálogo y las decisiones
// GO / REVIEW / NO_GO) y remite al bloque vivo para el presupuesto. Lo único que queda del presupuesto en él es una frase, marcada como
// histórica, para el caso en que el propio agente marcó «En riesgo» por un dato de presupuesto que esta pantalla ya no usa.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

const STATUSES = ["HEALTHY", "AT_RISK", "CRITICAL", "NEEDS_REVIEW"] as const;

const report = (status: CFOReport["financial_health_status"], over: Partial<NonNullable<CFOReport["data"]>> = {}): CFOReport => ({
  correlation_id: "r1",
  financial_health_status: status,
  recommendation: "GO",
  confidence: 0.85,
  data: {
    no_go_ratio: 0,
    budget_utilization: null,
    total_products_analyzed: 1,
    go_count: 1,
    review_count: 0,
    no_go_count: 0,
    total_campaigns: 1,
    active_campaigns: 1,
    total_daily_budget: 20,
    total_budget_hard_limit: 0,
    total_reserved: 0,
    total_committed: 0,
    total_spent: 0,
    risks: ["no budget allocations recorded yet: no objective has requested a spend approval yet"],
    evidence: ["1 products analyzed: 1 GO, 0 REVIEW, 0 NO_GO"],
    ...over,
  },
});

/** TODO lo que el veredicto pone en pantalla, en un solo texto. */
const everything = (view: VerdictView) => [view.title, view.status, view.detail, view.source, ...view.missing, ...view.inputs.flatMap((i) => [i.label, i.value])].join(" | ");

/** Lo que el veredicto no puede decir del presupuesto, sea cual sea el presupuesto vivo. */
const CLAIMS_ABOUT_THE_BUDGET = /no está cerca de su límite|cerca de agotarse|Uso del presupuesto|uso del presupuesto|presupuesto[^|]*saludable|no calculado|no hay presupuesto|sin presupuesto|límite del presupuesto/;

const live = (over: Partial<BudgetFigures> = {}): BudgetRead => ({
  authorised: true,
  budget: {
    name: "orchestrator-default",
    period: "monthly",
    currency: "EUR",
    currency_source: "accounting_currency",
    hard_limit: "1.00",
    soft_limit: null,
    reserved: "0.00",
    committed: "1.00",
    spent: "1.00",
    remaining: "0.00",
    ...over,
  },
  read_at: "2026-10-19T12:18:00Z",
});

const liveView = async (value: BudgetRead): Promise<BudgetLoadedView> => {
  const view = await readBudget({ getBudget: async () => value });
  assert.equal(view.kind, "loaded");
  return view as BudgetLoadedView;
};

// --- A · presupuesto agotado -------------------------------------------------------------------------------------------

test("A · con el presupuesto vivo agotado, ningún texto del veredicto lo contradice, sea cual sea el estado del informe", async () => {
  const budget = await liveView(live());
  assert.equal(budget.status, "exhausted");
  for (const status of STATUSES) {
    for (const utilization of [null, 0, 0.42, 0.95, 1.5]) {
      const text = everything(verdictView(report(status, { budget_utilization: utilization })));
      assert.doesNotMatch(text, CLAIMS_ABOUT_THE_BUDGET, `${status} · ${utilization}: ${text}`);
    }
  }
});

test("A2 · el veredicto «Saludable» de hoy (informe de septiembre, sin presupuesto) ya no dice nada del presupuesto", () => {
  const view = verdictView(report("HEALTHY"));
  assert.equal(view.status, "Saludable");
  assert.doesNotMatch(everything(view), /no está cerca|límite|calculado/);
  assert.equal(view.detail, "Pocas decisiones NO_GO entre los productos analizados.");
});

// --- B · presupuesto disponible --------------------------------------------------------------------------------------------

test("B · con el presupuesto vivo disponible, el veredicto tampoco lleva ningún «agotado» ni «cerca de su límite» fijo", async () => {
  const budget = await liveView(live({ hard_limit: "100.00", committed: "0.00", spent: "0.00", remaining: "100.00" }));
  assert.equal(budget.status, "available");
  for (const status of STATUSES) {
    const text = everything(verdictView(report(status, { budget_utilization: 0.95 })));
    assert.doesNotMatch(text, /agotad|cerca de su límite|cerca de agotarse|Uso del presupuesto/i, `${status}: ${text}`);
  }
});

// --- C · el presupuesto no se pudo leer --------------------------------------------------------------------------------------

test("C · si el presupuesto no se pudo leer, el veredicto no inventa ningún estado: es el mismo con o sin lectura", async () => {
  const failed = await readBudget({
    getBudget: async () => {
      throw new Error("fetch failed");
    },
  });
  assert.equal(failed.kind, "error");
  assert.equal(budgetView(unreadState("x")).kind, "unread");
  // `verdictView` no recibe el presupuesto: no hay forma de que su texto dependa de él.
  assert.equal(verdictView.length, 1);
  for (const status of STATUSES) assert.deepEqual(verdictView(report(status)), verdictView(report(status)));
});

// --- D · E · el informe antiguo no prevalece ------------------------------------------------------------------------------------

test("D · un informe antiguo SIN presupuesto no se presenta como el estado actual (ni «no hay presupuesto» ni «sin reservas»)", () => {
  const text = everything(verdictView(report("HEALTHY", { total_budget_hard_limit: 0, budget_utilization: null })));
  assert.doesNotMatch(text, /no hay presupuesto|sin presupuesto|no budget allocations|nada que informar|recorded yet/i);
  // Los avisos y las evidencias del informe (en inglés, de cuando se emitió) tampoco se pintan.
  assert.ok(!text.includes("no objective has requested"));
});

test("E · un `budget_utilization` viejo del informe no se usa como verdad actual: ni se enseña ni cambia el texto", () => {
  for (const utilization of [0.01, 0.42, 0.95, 2]) {
    const view = verdictView(report("HEALTHY", { budget_utilization: utilization, total_budget_hard_limit: 10, total_reserved: 3, total_committed: 2, total_spent: 2 }));
    assert.ok(!view.inputs.some((input) => /presupuesto/i.test(input.label)), "no hay ninguna fila de presupuesto");
    assert.deepEqual(view, verdictView(report("HEALTHY", { budget_utilization: null })), "el uso del informe no cambia nada");
  }
});

test("E2 · la fórmula antigua (reservado + comprometido + gastado) no vive en el veredicto", () => {
  const source = code("lib/cfo-verdict.ts");
  assert.doesNotMatch(source, /budget_utilization|total_budget_hard_limit|total_reserved|total_committed|total_spent|reserved|committed|\bspent\b/);
});

// --- F · «Uso del presupuesto no calculado» ----------------------------------------------------------------------------------------

test("F · «Uso del presupuesto no calculado» ya no existe, con presupuesto o sin él en el informe", () => {
  for (const utilization of [null, 0.3]) {
    const view = verdictView(report("HEALTHY", { budget_utilization: utilization }));
    assert.ok(!view.missing.some((item) => /Uso del presupuesto/.test(item)));
  }
  assert.doesNotMatch(read("lib/cfo-verdict.ts"), /Uso del presupuesto/);
});

test("F2 · lo que le falta al agente dice con claridad que NO evalúa el presupuesto y dónde está el vivo", () => {
  const view = verdictView(report("HEALTHY"));
  assert.ok(view.missing.some((item) => /No evalúa el presupuesto/.test(item) && /Presupuesto operativo/.test(item)), view.missing.join(" | "));
});

// --- G · sin presupuesto en el frontend --------------------------------------------------------------------------------------------

test("G · sin presupuesto, el veredicto no inventa ningún límite ni cifra de presupuesto", () => {
  const view = verdictView(report("AT_RISK", { no_go_ratio: 0.5, total_budget_hard_limit: 0, budget_utilization: null }));
  assert.doesNotMatch(everything(view), /límite|hard|techo|€|\b\d+[.,]\d{2}\b/);
});

// --- H · el estado «En riesgo» --------------------------------------------------------------------------------------------------------

test("H · «En riesgo» por NO_GO dice solo eso, sin hablar de presupuesto", () => {
  const view = verdictView(report("AT_RISK", { no_go_ratio: 0.5, budget_utilization: 0.95 }));
  assert.equal(view.detail, "Hay una proporción elevada de decisiones NO_GO entre los productos analizados.");
  assert.doesNotMatch(view.detail, /presupuesto/i);
});

test("H2 · «En riesgo» que NO explican los NO_GO (lo marcó un dato de presupuesto de entonces) lo dice como HISTÓRICO y remite al vivo", () => {
  for (const ratio of [0, 0.1, 0.2, null]) {
    const view = verdictView(report("AT_RISK", { no_go_ratio: ratio, budget_utilization: 0.95 }));
    assert.match(view.detail, /cuando emitió la evaluación/);
    assert.match(view.detail, /No es el estado actual/);
    assert.match(view.detail, /Presupuesto operativo/);
    assert.doesNotMatch(view.detail, /elevada de decisiones NO_GO|cerca de|agotar/);
  }
});

test("H3 · «Crítica» y «Requiere revisión» no hablan de presupuesto", () => {
  assert.doesNotMatch(verdictView(report("CRITICAL", { no_go_ratio: 0.9 })).detail, /presupuesto/i);
  assert.doesNotMatch(verdictView(report("NEEDS_REVIEW", { total_products_analyzed: 0, no_go_ratio: null })).detail, /presupuesto/i);
});

// --- La fuente --------------------------------------------------------------------------------------------------------------------------

test("I · la fuente del veredicto ya no dice que mira «las reservas del presupuesto»", () => {
  const view = verdictView(report("HEALTHY"));
  assert.doesNotMatch(view.source, /reservas del presupuesto/);
  assert.match(view.source, /No procede del registro financiero ni del presupuesto/);
  assert.match(view.source, /no confirma rentabilidad/);
});

// --- Una única verdad ------------------------------------------------------------------------------------------------------------------

test("J · no hay combinación presupuesto vivo × informe donde el veredicto y la sección digan cosas opuestas", async () => {
  const scenarios = [
    live(),
    live({ hard_limit: "100.00", committed: "0.00", spent: "0.00", remaining: "100.00" }),
    live({ hard_limit: "100.00", reserved: "25.00", committed: "40.00", spent: "40.00", remaining: "35.00" }),
    live({ hard_limit: "100.00", committed: "130.00", spent: "130.00", remaining: "-30.00" }),
  ];
  for (const scenario of scenarios) {
    const budget = await liveView(scenario);
    for (const status of STATUSES) {
      for (const utilization of [null, 0.1, 0.95]) {
        const text = everything(verdictView(report(status, { budget_utilization: utilization, no_go_ratio: 0.1 })));
        if (budget.status === "exhausted" || budget.status === "inconsistent") assert.doesNotMatch(text, /no está cerca|holgad|disponible/i);
        else assert.doesNotMatch(text, /agotad|sin saldo|no cuadra/i);
      }
    }
  }
});

test("K · `/cfo` pasa al veredicto SOLO el informe, y el presupuesto vivo solo a su propia sección", () => {
  const workspace = code("app/cfo/cfo-workspace.tsx");
  assert.match(workspace, /verdictView\(report\)/);
  assert.doesNotMatch(workspace, /verdictView\([^)]*budget/);
  assert.match(workspace, /<BudgetSection view=\{budget\} \/>/);
});

test("el veredicto sigue diciendo con cuánta información se emitió y que no ve el registro de pagos", () => {
  const view = verdictView(report("HEALTHY"));
  assert.equal(view.title, "Evaluación CFO — información parcial");
  assert.ok(view.missing.some((item) => /registro de pagos/.test(item)));
});
