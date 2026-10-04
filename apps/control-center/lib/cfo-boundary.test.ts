import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { MoneyAmount, Order, OrderItem, RevenueEntry, RevenueSummary } from "./api.ts";
import { marginSummary } from "./cfo-margin.ts";
import { planView } from "./cfo-plan.ts";
import { toText } from "./decimal.ts";
import { PROVENANCE_LABEL } from "./provenance.ts";
import { NO_DATA, summaryView } from "./revenue-view.ts";

// Las quince invariantes del CFO (M45, Commit 10), pedidas por el propietario.
//
// Unas se comprueban ejecutando la lógica y otras leyendo el código: que una regla se cumpla hoy por casualidad no
// sirve de nada si mañana alguien puede saltársela sin que nada se queje. Son las mismas dos vías que ya usan
// `demo-boundary.test.ts` y `dashboard-revenue-boundary.test.ts`.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

/** Todo lo que el CFO usa para calcular o enseñar dinero. */
const CFO_MODULES = [
  "lib/decimal.ts",
  "lib/provenance.ts",
  "lib/cfo-margin.ts",
  "lib/cfo-plan.ts",
  "lib/cfo-verdict.ts",
  "app/cfo/cfo-panels.tsx",
  "app/cfo/cfo-workspace.tsx",
  "app/cfo/page.tsx",
  "app/cfo/copy.ts",
];

const cfoFiles = () => readdirSync(join(ROOT, "app", "cfo")).filter((name) => /\.tsx?$/.test(name)).map((name) => `app/cfo/${name}`);

// --- Material de prueba ------------------------------------------------------------------------------------------

const money = (amount: string, currency = "EUR"): MoneyAmount => ({ amount, currency });

const item = (over: Partial<OrderItem> = {}): OrderItem => ({
  id: `i${over.line_number ?? 1}`,
  line_number: over.line_number ?? 1,
  product_id: "p1",
  supplier_id: null,
  supplier_quote_id: null,
  quantity: 1,
  allocated_quantity: 0,
  unit_price: money("50.0000"),
  line_total: money("50.0000"),
  unit_cost: money("30.0000"),
  cost_provenance: "supplier_quote",
  cost_source: "supplier_quote:q1",
  ...over,
});

const order = (id: string, items: OrderItem[]): Order => ({
  id,
  customer_ref: "sim",
  market: "eu",
  status: "PAID",
  is_simulated: true,
  amount_due: money("50.0000"),
  items,
  payments: [],
  refunds: [],
  fulfillments: [],
  created_at: "2026-10-01T09:00:00Z",
  paid_at: null,
  completed_at: null,
  cancelled_at: null,
  correlation_id: "c",
  attention_required: false,
  attention_reasons: [],
});

const entry = (orderId: string, kind: "CAPTURE" | "REFUND", amount: string, currency = "EUR"): RevenueEntry => ({
  id: `${orderId}${kind}${amount}${currency}`,
  kind,
  classification: "ORDER_PAYMENT",
  payment_event_id: "e",
  payment_id: "p",
  order_id: orderId,
  refund_id: null,
  capture_entry_id: null,
  amount,
  currency,
  occurred_at: "2026-10-02T10:00:00+00:00",
  recorded_at: "2026-10-02T10:00:00+00:00",
});

const summary = (over: Partial<RevenueSummary> = {}): RevenueSummary => ({
  period: {},
  entries: 0,
  verified: [],
  under_review: [],
  pending_evidence: { count: 0, by_currency: [] },
  consolidated_eur: null,
  non_aggregable_currencies: [],
  scope: { is_accounting_ledger: false, basis: "x", excludes: [] },
  ...over,
});

const complete = { entriesComplete: true };

// --- 1. Verified nunca consume PLAN ni DEMO ------------------------------------------------------------------------

test("1 · lo verificado no se construye con proyecciones ni con datos de demostración", () => {
  // Ningún módulo del CFO importa datos de demostración ni el P&L modelado que se retiró.
  for (const file of CFO_MODULES) {
    const imports = [...read(file).matchAll(/from\s+"([^"]+)"/g)].map((match) => match[1]);
    for (const target of imports) {
      assert.ok(!/\/demo\/|cfo-view|operations-view|economics-model|economics-baseline/.test(target), `${file} importa ${target}`);
    }
  }
  // Y en el código que calcula, una cifra verificada sólo se combina con otra verificada o, para el margen, con una
  // declarada — nunca con `planned(` ni con `demo(`.
  const margin = stripComments(read("lib/cfo-margin.ts"));
  assert.ok(!/\bplanned\(|\bdemo\(/.test(margin), "el margen no puede tocar una proyección ni una demostración");
  const plan = stripComments(read("lib/cfo-plan.ts"));
  // Ni produciéndolas ni nombrándolas: importar `verified` ya sería la puerta abierta.
  assert.ok(!/\bverified\b|\bdeclared\b|\bVerified\b|\bDeclared\b/.test(plan), "la proyección no toca lo verificado ni lo declarado");
});

test("1b · `add` y `subtract` sólo aceptan la misma procedencia (lo garantiza el tipo)", () => {
  const source = read("lib/provenance.ts");
  assert.match(source, /export function add<P extends Provenance>\(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>\)/);
  assert.match(source, /export function subtract<P extends Provenance>\(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>\)/);
  // La única combinación que cruza procedencias está en cfo-margin y degrada a «declarado».
  assert.match(read("lib/cfo-margin.ts"), /declared\(subtract\(net, cost\)\)/);
});

// --- 2 y 3. El margen y la cobertura -------------------------------------------------------------------------------

test("2 · el margen no existe con una sola línea sin coste", () => {
  const result = marginSummary(
    [entry("o1", "CAPTURE", "100.0000")],
    [order("o1", [item(), item({ line_number: 2, unit_cost: null, cost_provenance: null })])],
    complete,
  );
  assert.equal(result.margin, null);
  assert.equal(result.cost, null);
  assert.equal(result.coverage.complete, false);
});

test("3 · el margen aparece exactamente cuando la cobertura es del 100 %", () => {
  const result = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item(), item({ line_number: 2 })])], complete);
  assert.equal(result.coverage.percent, 100);
  assert.equal(result.coverage.complete, true);
  assert.equal(toText(result.margin!.value), "40.0000");
});

// --- 4. Monedas -----------------------------------------------------------------------------------------------------

test("4 · monedas distintas no se suman nunca, ni en el margen ni en el resumen", () => {
  const result = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000", "USD")],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  assert.equal(toText(result.revenue!.value), "100.0000");
  assert.deepEqual(result.otherCurrencies, ["USD"]);

  const view = summaryView(
    summary({
      entries: 2,
      verified: [
        { currency: "EUR", revenue: "100.0000", refunds: "0.0000", net: "100.0000", captures: 1, refund_count: 0 },
        { currency: "USD", revenue: "50.0000", refunds: "0.0000", net: "50.0000", captures: 1, refund_count: 0 },
      ],
      consolidated_eur: { currency: "EUR", revenue: "100.0000", refunds: "0.0000", net: "100.0000", under_review_outstanding: "0.0000" },
    }),
  );
  assert.equal(view.eur!.revenue, "100,00 €");
  assert.ok(!view.verified.some((row) => row.revenue.startsWith("150")));
});

// --- 5 y 6. PLAN y DEMO no alimentan lo verificado -------------------------------------------------------------------

test("5 · ninguna cifra PLAN entra en una magnitud verificada o declarada", () => {
  const workspace = read("app/cfo/cfo-workspace.tsx");
  // El plan se calcula aparte y sólo se pasa a su propia tarjeta.
  assert.match(workspace, /const plan = useMemo\(\(\) => planView\(/);
  assert.match(workspace, /<PlanCard plan=\{plan\} \/>/);
  assert.ok(!/marginSummary\([^)]*plan/.test(workspace), "el margen no recibe la proyección");
  const panels = read("app/cfo/cfo-panels.tsx");
  // En los paneles, cada cifra se pinta con la procedencia de su zona y no se mezclan en una misma tarjeta.
  const planCard = panels.slice(panels.indexOf("export function PlanCard"), panels.indexOf("// --- Evaluación del agente"));
  assert.ok(!/\bverified\b|\bdeclared\b|\bledger\b/.test(planCard), "la tarjeta PLAN no nombra lo verificado ni lo declarado");
});

test("6 · no queda ningún dato de demostración en el CFO", () => {
  for (const file of cfoFiles()) {
    const source = read(file);
    assert.ok(!/@\/lib\/demo/.test(source), `${file} importa datos de demostración`);
  }
  // Y las tarjetas que se sostenían sobre constantes se retiraron en lugar de disfrazarse.
  const retired = /DEMO_CASH|DEMO_TAX|runwayMonths|taxView|cashFlowSeries|payables\(|receivables\(|treasury\(|financialAlerts/;
  for (const file of cfoFiles()) assert.ok(!retired.test(read(file)), `${file} resucita una tarjeta retirada`);
});

// --- 7 y 8. Sin datos y errores --------------------------------------------------------------------------------------

test("7 · «sin datos» nunca se convierte en cero", () => {
  const empty = summaryView(summary());
  assert.equal(empty.eur, null);
  const result = marginSummary([], [], complete);
  assert.equal(result.margin, null);
  assert.equal(result.net, null);
  // Y en pantalla, un `null` se pinta como el texto «Sin datos», no como un importe.
  const panels = read("app/cfo/cfo-panels.tsx");
  assert.ok(panels.includes("margin.margin === null ? NO_DATA"), "el margen nulo se enseña como «Sin datos»");
  assert.ok(panels.includes("margin.cost === null ? NO_DATA"));
  assert.ok(!/\?\?\s*"0|\?\?\s*0\b/.test(stripComments(panels)), "algo cae a cero cuando no hay dato");
  assert.equal(NO_DATA, "Sin datos");
});

test("8 · un error del backend no se convierte en demostración ni en cero", () => {
  const page = read("app/cfo/page.tsx");
  const reads = page.split("\n").filter((line) => /settle[<(]/.test(line) && /api\.|read[A-Z]/.test(line));
  // Las tres lecturas de dinero pasan por settle(). (Desde el Commit 12 también pasan por settle() las del análisis
  // económico de cada producto y las del agente CFO: un error de lectura no es «sin análisis» ni «sin evaluación».)
  for (const money of [/api\.revenueSummary/, /readEntries\(/, /readOrders\(/]) {
    assert.equal(reads.filter((line) => money.test(line)).length, 1, `la lectura ${money} pasa por settle()`);
  }
  assert.ok(reads.length >= 3);
  for (const line of reads) assert.ok(!/\.catch\(/.test(line), `una lectura de dinero se traga el error: ${line.trim()}`);
  const panels = read("app/cfo/cfo-panels.tsx");
  assert.match(panels, /export function ReadFailed/);
  assert.match(panels, /No se ha sustituido por datos de demostración ni por un cero/);
  const workspace = read("app/cfo/cfo-workspace.tsx");
  assert.match(workspace, /if \(!entries\.ok \|\| !orders\.ok\) return null;/);
});

// --- 9. Cuadre con el registro ---------------------------------------------------------------------------------------

test("9 · las cifras verificadas son las que dio /api/revenue/*, sin recalcular", () => {
  const data = summary({
    entries: 3,
    verified: [{ currency: "EUR", revenue: "703.8000", refunds: "10.0000", net: "693.8000", captures: 9, refund_count: 1 }],
    consolidated_eur: { currency: "EUR", revenue: "703.8000", refunds: "10.0000", net: "693.8000", under_review_outstanding: "42.5000" },
  });
  const view = summaryView(data);
  assert.equal(view.eur!.revenue, "703,80 €");
  assert.equal(view.eur!.net, "693,80 €");
  // La vista formatea el texto del backend; no vuelve a restar ingresos menos reembolsos por su cuenta.
  assert.ok(!/revenue\s*-\s*refunds|revenue\s*−\s*refunds/.test(stripComments(read("lib/revenue-view.ts"))));
});

// --- 10. Sin float ---------------------------------------------------------------------------------------------------

test("10 · ningún float entra en una cifra de dinero", () => {
  for (const file of ["lib/cfo-margin.ts", "lib/cfo-plan.ts", "lib/provenance.ts", "app/cfo/cfo-panels.tsx", "app/cfo/cfo-workspace.tsx"]) {
    const source = stripComments(read(file));
    assert.ok(!/\bparseFloat\b|\.toFixed\(/.test(source), `${file} usa aritmética de coma flotante`);
    // `Number(` sólo se admite donde no hay dinero: no aparece en ninguno de estos módulos.
    assert.ok(!/\bNumber\(/.test(source), `${file} convierte algo a number`);
  }
  // La única aritmética con dinero vive en decimal.ts, y es sobre `bigint`.
  const decimal = stripComments(read("lib/decimal.ts"));
  assert.match(decimal, /bigint/);
  assert.ok(!/\bparseFloat\b|\.toFixed\(/.test(decimal));
  assert.ok(!/Number\((?!\.isSafeInteger)/.test(decimal.replace(/Number\.isSafeInteger/g, "")), "decimal.ts no convierte importes a number");
});

// --- 11. Procedencia del dato declarado --------------------------------------------------------------------------------

test("11 · un coste sin procedencia declarada no se usa", () => {
  const withoutProvenance = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item({ cost_provenance: null })])], complete);
  assert.equal(withoutProvenance.margin, null);
  assert.equal(withoutProvenance.coverage.linesWithCost, 0);
  // Y la que sí tiene procedencia la enseña.
  const withProvenance = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item()])], complete);
  assert.deepEqual(withProvenance.orders[0].costProvenances, ["supplier_quote"]);
  assert.match(read("app/cfo/cfo-panels.tsx"), /costProvenances\.join/);
});

// --- 12. Ninguna constante disfrazada de registro -----------------------------------------------------------------------

test("12 · ninguna tarjeta usa una constante como si fuera un dato del registro", () => {
  const panels = read("app/cfo/cfo-panels.tsx");
  // Todo importe que se pinta viene de una lectura (`summary`, `margin`, `plan`), nunca de un literal con decimales.
  const literals = [...stripComments(panels).matchAll(/\d[\d.]*,\d{2,4}|\d[\d,]*\.\d{2,4}/g)].map((match) => match[0]);
  assert.deepEqual(literals, [], `hay importes escritos a mano en los paneles: ${literals.join(", ")}`);
  for (const file of cfoFiles()) {
    const source = stripComments(read(file));
    assert.ok(!/\bconst\s+\w*(CASH|REVENUE|PROFIT|MARGIN|TAX)\w*\s*=\s*\d/.test(source), `${file} define una cifra a mano`);
  }
});

// --- 13. El veredicto, aparte ------------------------------------------------------------------------------------------

test("13 · el veredicto del agente vive fuera de las magnitudes financieras", () => {
  const workspace = read("app/cfo/cfo-workspace.tsx");
  const verdictAt = workspace.indexOf('aria-label="Evaluación del agente CFO"');
  const zonesEnd = workspace.indexOf('aria-label="Proyección"');
  assert.ok(verdictAt > zonesEnd, "el veredicto va después de las tres zonas, en su propia sección");
  const panels = read("app/cfo/cfo-panels.tsx");
  const card = panels.slice(panels.indexOf("export function VerdictCard"), panels.indexOf("// --- Lo que esta pantalla"));
  assert.ok(!/DataProvenanceBadge/.test(card), "el veredicto no lleva etiqueta de procedencia de dinero: no es una magnitud");
  assert.ok(!/formatMoney|amountText/.test(card), "el veredicto no pinta importes");
});

// --- 14. Las etiquetas sobreviven al periodo ------------------------------------------------------------------------------

test("14 · las etiquetas de procedencia no dependen del periodo ni de que haya datos", () => {
  const panels = read("app/cfo/cfo-panels.tsx");
  // La etiqueta sale de un mapa fijo por zona, no de los datos.
  assert.match(panels, /const BADGE: Record<Provenance, DataProvenance> = \{/);
  assert.ok(!/days\s*[=<>]|period\b.*BADGE/.test(panels.slice(panels.indexOf("const BADGE"), panels.indexOf("const ZONE_ICON"))));
  // Y el componente de la cifra pinta su badge siempre, haya dato o no.
  const figure = panels.slice(panels.indexOf("function Figure("), panels.indexOf("// --- Zona 1"));
  const badgeLine = figure.split("\n").find((line) => line.includes("<DataProvenanceBadge"));
  assert.notEqual(badgeLine, undefined, "la cifra siempre lleva su etiqueta");
  assert.match(badgeLine!.trim(), /^<DataProvenanceBadge status=\{BADGE\[provenance\]\} compact/);
  // Nada la condiciona: ni un ternario, ni un `&&`, ni que falte el dato.
  assert.ok(!/[?&]/.test(badgeLine!), `la etiqueta está condicionada: ${badgeLine!.trim()}`);
});

// --- 15. Estado vacío honesto ---------------------------------------------------------------------------------------------

test("15 · sin datos, la pantalla lo dice y no enseña ni una cifra inventada", () => {
  const empty = summaryView(summary());
  assert.equal(empty.hasAnyData, false);
  assert.equal(empty.verified.length, 0);
  const margin = marginSummary([], [], complete);
  assert.equal(margin.coverage.orders, 0);
  assert.equal(margin.margin, null);
  const plan = planView([], new Map());
  assert.equal(plan.totalPerOrder, null);
  assert.equal(plan.blockedBy, "no_analyses");
  // Y hay un estado vacío escrito para cada zona.
  const panels = read("app/cfo/cfo-panels.tsx");
  assert.ok((panels.match(/<EmptyState/g) ?? []).length >= 3, "cada zona tiene su estado vacío");
});

// --- Vocabulario -----------------------------------------------------------------------------------------------------

test("el CFO usa el mismo vocabulario de procedencia que el Panel, y ninguna etiqueta dice «real»", () => {
  const badge = read("components/data-provenance-badge.tsx");
  for (const provenance of Object.keys(PROVENANCE_LABEL)) {
    const mapped = provenance === "verified" ? "ledger" : provenance;
    assert.ok(new RegExp(`\\b${mapped}:\\s*\\{`).test(badge), `falta la etiqueta de ${provenance}`);
  }
  assert.ok(!/label:\s*"Real"/i.test(badge));
  for (const file of CFO_MODULES) {
    assert.ok(!/\breal(es|idad)?\b/i.test(read(file)), `${file} dice «real» de unas cifras que no lo demuestran`);
  }
});

test("el CFO sólo lee: ninguna llamada suya a la API escribe", () => {
  for (const file of cfoFiles()) {
    const source = read(file);
    for (const match of source.matchAll(/\bapi\.(\w+)/g)) {
      assert.match(`api.${match[1]}`, /api\.(list|get|revenue)\w*$/, `${file}: api.${match[1]} no parece una lectura`);
    }
    assert.ok(!/method\s*:/.test(source), `${file} fija un método HTTP`);
    assert.ok(!/\bfetch\(/.test(source), `${file} llama a fetch directamente`);
  }
});

test("lo que la pantalla no puede calcular se declara, en vez de aparentarlo", () => {
  const panels = read("app/cfo/cfo-panels.tsx");
  for (const concept of ["IVA", "OSS", "caja", "runway", "comisiones", "beneficio neto", "EBITDA", "cuentas por pagar"]) {
    assert.ok(panels.includes(concept), `la lista de lo que no se puede calcular no menciona ${concept}`);
  }
});
