import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution, Approval, PipelineReview, Product } from "./api.ts";
import type { CatalogEntry, DashboardReads } from "./dashboard-reads.ts";
import {
  activityView,
  agentsKpiView,
  decisionsKpiView,
  decisionsView,
  demoContext,
  opportunitiesView,
  readIssues,
  runsPerDay,
  unavailableText,
} from "./dashboard-view.ts";
import { economicAnalysisFixture, quoteFixture } from "./quote-fixture.ts";
import { READ_UNAVAILABLE_VALUE, READ_UNREAD_TEXT, type ReadState } from "./read-state.ts";
import { agent, approval, execution, LOOKS_LIKE_ABSENCE, NOW, product, review, TECHNICAL } from "./read-test-support.ts";
import type { ApprovalRequest } from "./approvals-view.ts";

// Las vistas del Panel sobre estados de lectura (M46, Commit 6): qué se enseña cuando una lectura es `loaded`, `empty`,
// `unread` o `error`. Regla común: un `error` o un `unread` NUNCA produce un 0, un porcentaje, una suma ni un «Sin datos».

const loaded = <T>(data: T): ReadState<T> => ({ kind: "loaded", data });
const empty = { kind: "empty" } as const;
const failed = (message = "No se pudieron cargar los datos de prueba."): ReadState<never> => ({ kind: "error", message });
const unread = (reason = "no se leyó"): ReadState<never> => ({ kind: "unread", reason });

const agents = [agent("a1"), agent("a2", "OFFLINE")];
const entry = (id: string, over: Partial<CatalogEntry> = {}): CatalogEntry => ({
  product: product(id),
  projectCode: `AMZ-00${id.replace(/\D/g, "")}`,
  quotes: empty,
  economics: empty,
  legal: empty,
  storefronts: empty,
  campaigns: empty,
  ...over,
});

const demoRequest = { id: "demo-1", status: "PENDING", isDemo: true, severity: "Media", requestedAt: NOW } as unknown as ApprovalRequest;

// --- «Agentes en línea» ---------------------------------------------------------------------------------------------

test("agentes `loaded`: el cociente sale de la lectura; `empty`: «Sin agentes», no «0 / 0» ni «0 %»", () => {
  const value = agentsKpiView(loaded(agents), loaded([execution("e1", "a1")]));
  const none = agentsKpiView(empty, loaded([]));

  assert.equal(value.kind, "value");
  assert.equal(value.value, "1 / 2");
  assert.match(value.caption, /50\s?% operativos/);
  assert.equal(none.kind, "empty");
  assert.equal(none.value, "Sin agentes");
  assert.doesNotMatch(none.value + none.caption, /0 \/ 0|%/);
});

test("agentes `error` o `unread`: ni «0 / 0», ni porcentaje, ni «Sin agentes»", () => {
  for (const state of [failed(), unread()]) {
    const view = agentsKpiView(state, loaded([]));

    assert.equal(view.kind, state.kind);
    assert.doesNotMatch(view.value, /\d|%/);
    assert.doesNotMatch(`${view.value} ${view.caption}`, /0 \/ 0|%|Sin agentes|Sin datos|No hay/);
  }
  assert.equal(agentsKpiView(failed(), loaded([])).value, READ_UNAVAILABLE_VALUE);
  assert.equal(agentsKpiView(unread(), loaded([])).value, READ_UNREAD_TEXT);
});

test("agentes `loaded` con el log de ejecuciones caído: la cifra sigue siendo cierta y dice que las ejecuciones no están", () => {
  const view = agentsKpiView(loaded(agents), failed());

  assert.equal(view.kind, "value");
  assert.equal(view.value, "1 / 2");
  assert.match(view.caption, /ejecuciones no disponibles/);
});

// --- «Aprobaciones pendientes» y «Decisiones necesarias» ------------------------------------------------------------

test("decisiones: con las dos lecturas válidas se cuentan las reales y las de demostración, por separado", () => {
  const view = decisionsView({ approvals: loaded([approval("ap1")]), reviews: loaded([review("rv1")]), demo: [demoRequest], now: NOW });

  assert.equal(view.kind, "ready");
  if (view.kind !== "ready") return;
  assert.equal(view.pending, 3);
  assert.equal(view.fromBackend, 2);
  const kpi = decisionsKpiView(view);
  assert.equal(kpi.value, "3");
  assert.match(kpi.caption, /2 del backend · 1 de demostración/);
});

test("decisiones: el cero existe solo si las DOS lecturas del backend son válidas", () => {
  const nothing = decisionsView({ approvals: empty, reviews: empty, demo: [], now: NOW });
  const kpi = decisionsKpiView(nothing);

  assert.equal(nothing.kind, "ready");
  assert.deepEqual(kpi, { kind: "empty", value: "0", caption: "Nada esperando tu decisión." });
});

test("decisiones: si una lectura del backend falla NO hay conteo ni lista parcial ni «0 del backend»", () => {
  for (const bad of [failed(), unread()]) {
    for (const [approvals, reviews] of [
      [bad, loaded([review("rv1")])],
      [loaded([approval("ap1")]), bad],
      [bad, bad],
    ] as Array<[ReadState<Approval[]>, ReadState<PipelineReview[]>]>) {
      const view = decisionsView({ approvals, reviews, demo: [demoRequest], now: NOW });
      assert.equal(view.kind, "unavailable");
      assert.ok(!("requests" in view) && !("pending" in view), "una lectura caída no deja una lista parcial");
      const kpi = decisionsKpiView(view);
      assert.ok(kpi.kind === "error" || kpi.kind === "unread");
      assert.doesNotMatch(kpi.value, /\d/);
      assert.doesNotMatch(`${kpi.value} ${kpi.caption}`, /0 del backend|Nada esperando|Sin datos|No hay/);
    }
  }
});

test("decisiones: el texto del fallo nombra qué no se leyó y no es técnico", () => {
  const view = decisionsView({ approvals: failed(), reviews: loaded([]), demo: [], now: NOW });

  assert.equal(view.kind, "unavailable");
  if (view.kind !== "unavailable") return;
  assert.deepEqual(view.sources, ["las aprobaciones"]);
  assert.equal(view.message, unavailableText(["las aprobaciones"]));
  assert.doesNotMatch(view.message, TECHNICAL);
});

// --- «Actividad empresarial» ----------------------------------------------------------------------------------------

test("actividad: con agentes y ejecuciones válidas salen las ejecuciones REALES, sin demostración", () => {
  const view = activityView({ agents: loaded(agents), executions: loaded([execution("e1", "a1")]), now: NOW, limit: 5 });

  assert.equal(view.kind, "rows");
  if (view.kind !== "rows") return;
  assert.equal(view.usingDemoRuns, false);
  assert.equal(view.rows.find((row) => row.id === "a1")?.runs, 1);
  assert.equal(view.runsPerDay.reduce((sum, count) => sum + count, 0), 1);
});

test("actividad: la demostración solo se activa con un log VÁLIDO y vacío, y se dice", () => {
  const view = activityView({ agents: loaded(agents), executions: empty, now: NOW, limit: 5 });

  assert.equal(view.kind, "rows");
  if (view.kind === "rows") assert.equal(view.usingDemoRuns, true);
});

test("actividad: un log que no se pudo leer NO es un log vacío: no hay demostración, hay un error", () => {
  for (const bad of [failed(), unread()]) {
    const view = activityView({ agents: loaded(agents), executions: bad, now: NOW, limit: 5 });

    assert.equal(view.kind, "unavailable");
    assert.ok(!("rows" in view), "no se enseñan filas construidas sobre ejecuciones inventadas");
    assert.ok(!("runsPerDay" in view), "ni las barras de siete días");
    if (view.kind === "unavailable") assert.deepEqual(view.sources, ["el log de ejecuciones"]);
  }
});

test("actividad: sin lectura de agentes no hay tarjetas, ni «Sin agentes registrados»; con registro vacío sí", () => {
  const bad = activityView({ agents: failed(), executions: loaded([]), now: NOW, limit: 5 });
  const none = activityView({ agents: empty, executions: loaded([]), now: NOW, limit: 5 });

  assert.equal(bad.kind, "unavailable");
  assert.equal(none.kind, "no-agents");
});

test("actividad: si caen las dos lecturas, el mensaje nombra las dos", () => {
  const view = activityView({ agents: failed(), executions: failed(), now: NOW, limit: 5 });

  assert.equal(view.kind, "unavailable");
  if (view.kind === "unavailable") {
    assert.deepEqual(view.sources, ["los agentes", "el log de ejecuciones"]);
    assert.equal(view.state, "error");
  }
});

test("runsPerDay: cuenta por día los siete últimos y no inventa ejecuciones", () => {
  const counts = runsPerDay([execution("e1", "a1", NOW - 60_000), execution("e2", "a1", NOW - 2 * 86_400_000)], NOW);

  assert.equal(counts.length, 7);
  assert.equal(counts.reduce((sum, count) => sum + count, 0), 2);
  assert.deepEqual(runsPerDay([], NOW), [0, 0, 0, 0, 0, 0, 0]);
});

// --- «Oportunidades» ------------------------------------------------------------------------------------------------

const products = [product("p1"), product("p2"), product("p3")];

test("oportunidades: un catálogo que no se pudo leer es un error, no «Todavía no hay catálogo»", () => {
  const bad = opportunitiesView({ products: failed(), catalog: [], limit: 5 });
  const none = opportunitiesView({ products: empty, catalog: [], limit: 5 });

  assert.equal(bad.kind, "unavailable");
  assert.equal(none.kind, "no-catalog");
  assert.notDeepEqual(bad, none);
});

test("oportunidades: la fase sale de las cinco lecturas del producto cuando todas son válidas", () => {
  const view = opportunitiesView({
    products: loaded(products),
    catalog: [
      entry("p1", { quotes: loaded([quoteFixture()]) }),
      entry("p2", { quotes: loaded([quoteFixture()]), economics: loaded([economicAnalysisFixture()]), legal: loaded([{}] as never) }),
      entry("p3"),
    ],
    limit: 5,
  });

  assert.equal(view.kind, "rows");
  if (view.kind !== "rows") return;
  const stages = Object.fromEntries(view.rows.map((row) => [row.productId, row.stage]));
  assert.deepEqual(stages.p1, { kind: "value", value: "Evaluación" });
  assert.deepEqual(stages.p2, { kind: "value", value: "Validación" });
  assert.deepEqual(stages.p3, { kind: "value", value: "En observación" });
});

test("oportunidades: «En observación» solo cuando las cinco lecturas confirman que no hay nada (todas `empty`)", () => {
  const view = opportunitiesView({ products: loaded([product("p1")]), catalog: [entry("p1")], limit: 5 });

  assert.equal(view.kind === "rows" && view.rows[0].stage.kind === "value" && view.rows[0].stage.value, "En observación");
});

for (const read of ["quotes", "economics", "legal", "storefronts", "campaigns"] as const) {
  test(`oportunidades: si falla la lectura de ${read}, la fase es «No disponible», no «En observación» ni una fase más baja`, () => {
    const view = opportunitiesView({
      products: loaded([product("p1")]),
      catalog: [entry("p1", { [read]: failed() })],
      limit: 5,
    });

    assert.equal(view.kind, "rows");
    if (view.kind !== "rows") return;
    assert.equal(view.rows[0].stage.kind, "error");
    assert.ok(!("value" in view.rows[0].stage));
    const text = view.rows[0].stage.kind === "error" ? view.rows[0].stage.text : "";
    assert.doesNotMatch(text, LOOKS_LIKE_ABSENCE);
    assert.doesNotMatch(text, TECHNICAL);
  });
}

test("oportunidades: el margen necesita proveedores y economía; si cualquiera falla no hay margen ni se inventa el de demostración", () => {
  for (const read of ["quotes", "economics"] as const) {
    const view = opportunitiesView({ products: loaded([product("p1")]), catalog: [entry("p1", { [read]: failed() })], limit: 5 });

    assert.equal(view.kind === "rows" && view.rows[0].margin.kind, "error");
  }
  // Y si lo que falla es otra lectura (la tienda), el margen —que no depende de ella— sigue siendo cierto.
  const unaffected = opportunitiesView({ products: loaded([product("p1")]), catalog: [entry("p1", { storefronts: failed() })], limit: 5 });
  assert.equal(unaffected.kind === "rows" && unaffected.rows[0].margin.kind, "value");
});

test("oportunidades: sin análisis económico (lectura válida y vacía) el margen es del modelo con supuestos de demostración y se rotula así", () => {
  const view = opportunitiesView({ products: loaded([product("p1")]), catalog: [entry("p1")], limit: 5 });
  const withAnalysis = opportunitiesView({
    products: loaded([product("p1")]),
    catalog: [entry("p1", { quotes: loaded([quoteFixture()]), economics: loaded([economicAnalysisFixture()]) })],
    limit: 5,
  });

  const margin = view.kind === "rows" ? view.rows[0].margin : null;
  const real = withAnalysis.kind === "rows" ? withAnalysis.rows[0].margin : null;
  assert.equal(margin?.kind === "value" && margin.value.isReal, false);
  assert.equal(real?.kind === "value" && real.value.isReal, true);
});

test("oportunidades: un producto del que no se leyó el pipeline (fuera del tope) es `unread`, NO «En observación»", () => {
  const view = opportunitiesView({ products: loaded(products), catalog: [entry("p1")], limit: 5 });

  assert.equal(view.kind, "rows");
  if (view.kind !== "rows") return;
  const byId = Object.fromEntries(view.rows.map((row) => [row.productId, row]));
  assert.equal(byId.p1.stage.kind, "value");
  for (const id of ["p2", "p3"]) {
    assert.equal(byId[id].stage.kind, "unread", `${id}: la fase no se inventa`);
    assert.equal(byId[id].margin.kind, "unread", `${id}: el margen no se inventa`);
  }
});

test("oportunidades: respeta el tope de filas", () => {
  const view = opportunitiesView({ products: loaded(products), catalog: [], limit: 2 });

  assert.equal(view.kind === "rows" && view.rows.length, 2);
});

// --- El producto de las solicitudes de demostración ----------------------------------------------------------------

test("demoContext: solo usa productos con las cinco lecturas válidas; ninguno con una lectura caída", () => {
  const ok = entry("p1", { quotes: loaded([quoteFixture()]) });
  const broken = entry("p2", { quotes: loaded([quoteFixture(), quoteFixture(), quoteFixture()]), legal: failed() });

  assert.equal(demoContext([ok, broken])?.product.id, "p1");
  assert.equal(demoContext([broken]), undefined);
  assert.equal(demoContext([]), undefined);
});

test("demoContext: gana el producto más avanzado entre los completos", () => {
  const shallow = entry("p1");
  const deep = entry("p2", { quotes: loaded([quoteFixture()]), economics: loaded([economicAnalysisFixture()]) });

  assert.equal(demoContext([shallow, deep])?.product.id, "p2");
});

// --- Qué lecturas fallaron ------------------------------------------------------------------------------------------

const reads = (over: Partial<DashboardReads> = {}): DashboardReads => ({
  products: loaded(products),
  agents: loaded(agents),
  executions: empty,
  approvals: empty,
  reviews: empty,
  catalog: [],
  unreadProductIds: [],
  ...over,
});
const okSettled = { ok: true, data: null } as const;
const badSettled = { ok: false, message: "x" } as const;

test("readIssues: solo cuenta los errores; lo no leído por diseño (fuera del tope) y lo vacío no son un fallo", () => {
  assert.deepEqual(readIssues(reads(), { summary: okSettled, series: okSettled, entries: okSettled }), []);
  assert.deepEqual(
    readIssues(reads({ unreadProductIds: ["p9"], approvals: empty }), { summary: okSettled, series: okSettled, entries: okSettled }),
    [],
  );
});

test("readIssues: nombra cada lectura caída, agrega los productos y avisa de los ingresos", () => {
  const issues = readIssues(
    reads({
      agents: failed(),
      approvals: failed(),
      catalog: [entry("p1", { legal: failed() }), entry("p2", { campaigns: failed() }), entry("p3")],
    }),
    { summary: badSettled, series: okSettled, entries: okSettled },
  );

  assert.deepEqual(
    issues.map((issue) => issue.label),
    ["los agentes", "las aprobaciones", "el pipeline de 2 productos", "los ingresos"],
  );
});

// --- Invariantes sobre TODAS las combinaciones ----------------------------------------------------------------------

const STATES: Array<[string, ReadState<never[]>]> = [
  ["loaded", loaded([])],
  ["empty", empty],
  ["error", failed()],
  ["unread", unread()],
];
const usable = (state: ReadState<unknown>) => state.kind === "loaded" || state.kind === "empty";

test("invariantes: en las 256 combinaciones de agentes × ejecuciones × aprobaciones × revisiones, un fallo nunca se vuelve un hecho", () => {
  let combos = 0;
  for (const [, a] of STATES) {
    for (const [, x] of STATES) {
      for (const [, p] of STATES) {
        for (const [, r] of STATES) {
          combos += 1;
          const agentsState = (a.kind === "loaded" ? loaded(agents) : a) as ReadState<Agent[]>;
          const executionsState = x as ReadState<AgentExecution[]>;
          const approvalsState = p as ReadState<Approval[]>;
          const reviewsState = r as ReadState<PipelineReview[]>;

          const kpi = agentsKpiView(agentsState, executionsState);
          const activity = activityView({ agents: agentsState, executions: executionsState, now: NOW, limit: 5 });
          const decisions = decisionsView({ approvals: approvalsState, reviews: reviewsState, demo: [], now: NOW });
          const decisionsKpi = decisionsKpiView(decisions);

          assert.equal(kpi.kind === "error" || kpi.kind === "unread", !usable(agentsState));
          assert.equal(activity.kind === "unavailable", !usable(agentsState) || !usable(executionsState));
          assert.equal(decisions.kind === "unavailable", !usable(approvalsState) || !usable(reviewsState));
          assert.equal(decisionsKpi.kind === "error" || decisionsKpi.kind === "unread", decisions.kind === "unavailable");
          // La demostración solo con un log válido y vacío.
          if (activity.kind === "rows") assert.equal(activity.usingDemoRuns, executionsState.kind === "empty");
          // Y ningún fallo produce una cifra ni un texto de ausencia.
          for (const view of [kpi, decisionsKpi]) {
            if (view.kind === "error" || view.kind === "unread") {
              assert.doesNotMatch(view.value, /\d|%/);
              assert.doesNotMatch(`${view.value} ${view.caption}`, /Sin datos|No hay|Nada esperando|Sin agentes|0 del backend/);
            }
          }
        }
      }
    }
  }
  assert.equal(combos, 256);
});

test("`empty` y `error` se distinguen en TODAS las vistas: ni el valor ni el texto coinciden", () => {
  const pairs = [
    [agentsKpiView(empty, empty), agentsKpiView(failed(), empty)],
    [decisionsKpiView(decisionsView({ approvals: empty, reviews: empty, demo: [], now: NOW })), decisionsKpiView(decisionsView({ approvals: failed(), reviews: empty, demo: [], now: NOW }))],
  ] as const;

  for (const [valid, broken] of pairs) {
    assert.notEqual(valid.kind, broken.kind);
    assert.notEqual(valid.value, broken.value);
    assert.notEqual(valid.caption, broken.caption);
  }
  assert.notEqual(
    activityView({ agents: empty, executions: empty, now: NOW, limit: 5 }).kind,
    activityView({ agents: failed(), executions: empty, now: NOW, limit: 5 }).kind,
  );
  assert.notEqual(
    opportunitiesView({ products: empty, catalog: [], limit: 5 }).kind,
    opportunitiesView({ products: failed(), catalog: [], limit: 5 }).kind,
  );
});

test("un fallo posterior no cambia una verdad conocida por una mentira: las vistas son funciones puras del estado recibido", () => {
  const before = agentsKpiView(loaded(agents), loaded([]));
  agentsKpiView(failed(), failed()); // otra lectura, fallida, en medio
  const after = agentsKpiView(loaded(agents), loaded([]));

  assert.deepEqual(before, after);
  const sample: Product[] = [product("p1")];
  assert.deepEqual(opportunitiesView({ products: loaded(sample), catalog: [], limit: 5 }), opportunitiesView({ products: loaded(sample), catalog: [], limit: 5 }));
});
