import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { REVENUE_SCOPE_NOTE } from "./revenue-view.ts";

// Frontera de los ingresos del Panel (M45, ADR 0030): lo medido no se mezcla con lo demostrativo, y el Panel solo lee.
//
// El resto de pruebas fijan lo que la vista DICE; estas fijan lo que el código NO PUEDE HACER, mirando el código mismo,
// igual que `demo-boundary.test.ts` y `server-api-boundary.test.ts`. Un cambio que rompa una de estas reglas tiene que
// romper una prueba, no pasar desapercibido.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF, y estas pruebas miran el texto. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");

/** Todo lo que sale del registro de ingresos: nada de esto puede depender de datos inventados ni de un modelo. */
const MEASURED = ["lib/revenue-view.ts", "lib/revenue-query.ts", "components/revenue-bars.tsx", "app/dashboard/revenue-panels.tsx"];

/** Módulos que modelan o inventan cifras económicas: ni de lejos pueden alimentar los ingresos. */
const MODELLED = /demo|cfo-view|operations-view|economics|projects-view|storefront|sourcing-view/;

function importsOf(source: string): string[] {
  return [...source.matchAll(/from\s+"([^"]+)"/g)].map((match) => match[1]);
}

function dashboardFiles(): string[] {
  return readdirSync(join(ROOT, "app", "dashboard")).filter((name) => /\.tsx?$/.test(name)).map((name) => `app/dashboard/${name}`);
}

test("los ingresos medidos no importan datos de demostración ni ningún modelo económico", () => {
  for (const file of MEASURED) {
    for (const target of importsOf(read(file))) {
      assert.ok(!MODELLED.test(target), `${file} importa ${target}: lo medido no puede depender de lo modelado`);
    }
  }
});

test("el Panel ya no contiene el P&L, los pedidos ni las ventas de demostración", () => {
  const forbidden =
    /\b(buildPnl|scalePnl|withDeltas|monthFactor|salesSeries|SalesPoint|buildOrders|DEMO_SALE|demoQuotes|demoSku)\b|cfo-view|operations-view/;
  for (const file of [...dashboardFiles(), "lib/dashboard-view.ts"]) {
    assert.ok(!forbidden.test(read(file)), `${file} todavía construye o importa ventas y beneficio modelados`);
  }
});

test("el Panel solo lee: toda llamada a api.* es de lectura", () => {
  const calls: string[] = [];
  for (const file of dashboardFiles()) {
    const source = read(file);
    // Cualquier acceso a `api.<algo>`, se llame o no: guardar la función en una variable no la esconde.
    for (const match of source.matchAll(/\bapi\.(\w+)/g)) calls.push(`${file}: api.${match[1]}`);
    assert.ok(!/\bfetch\(/.test(source), `${file} llama a fetch directamente`);
    assert.ok(!/method\s*:/.test(source), `${file} fija un método HTTP`);
  }
  assert.ok(calls.length > 0, "el Panel debería llamar a la API");
  for (const call of calls) {
    assert.match(call, /api\.(list|get|revenue)\w*$/, `${call} no parece una lectura`);
  }
});

test("las lecturas de ingresos de api.ts son GET sin cuerpo, sin método y sin clave de idempotencia", () => {
  const source = read("lib/api.ts");
  const start = source.indexOf("revenueSummary:");
  const end = source.indexOf("createObjective:", start);
  assert.ok(start > 0 && end > start, "no se encuentra el bloque de lecturas de ingresos en lib/api.ts");
  const block = source.slice(start, end);
  assert.deepEqual(
    [...block.matchAll(/\b(revenue\w+):/g)].map((match) => match[1]),
    ["revenueSummary", "revenueSeries", "revenueEntries"],
  );
  for (const forbidden of ["method", "body", "keyed(", "idempotency", "Idempotency", "POST", "PUT", "PATCH", "DELETE"]) {
    assert.ok(!block.includes(forbidden), `una lectura de ingresos contiene «${forbidden}»`);
  }
  assert.equal([...block.matchAll(/request</g)].length, 3, "cada lectura hace exactamente una petición");
});

test("la ruta de los ingresos solo se construye hacia /api/revenue/{summary,series,entries}", () => {
  const source = read("lib/revenue-query.ts");
  assert.match(source, /`\/api\/revenue\/\$\{resource\}/);
  assert.match(source, /type RevenueResource = "summary" \| "series" \| "entries"/);
});

test("un error de lectura no se sustituye por datos de demostración en la página", () => {
  const page = read("app/dashboard/page.tsx");
  const revenueLines = page.split("\n").filter((line) => /api\.revenue\w+\(/.test(line));
  assert.equal(revenueLines.length, 3);
  for (const line of revenueLines) {
    assert.match(line, /settle\(/, "cada lectura de ingresos pasa por settle(): dato o error visible");
    assert.ok(!/\.catch\(/.test(line), "una lectura de ingresos no se traga el error con .catch");
  }
  // El panel enseña el error: no hay ninguna rama que lo cambie por otra cosa.
  const panels = read("app/dashboard/revenue-panels.tsx");
  assert.match(panels, /export function RevenueUnavailable/);
  assert.match(panels, /No se ha sustituido por datos de demostración/);
});

test("todo lo que sale del registro se etiqueta «registro verificado», y solo eso", () => {
  const panels = read("app/dashboard/revenue-panels.tsx");
  const statuses = [...panels.matchAll(/status="(\w+)"/g)].map((match) => match[1]);
  assert.ok(statuses.length >= 4, "cada tarjeta de ingresos lleva su etiqueta");
  assert.ok(statuses.every((status) => status === "ledger"), `una tarjeta de ingresos no es del registro: ${statuses.join(", ")}`);

  const workspace = read("app/dashboard/dashboard-workspace.tsx");
  const start = workspace.indexOf("function RevenueKpi");
  const end = workspace.indexOf("export function DashboardWorkspace");
  const kpi = workspace.slice(start, end);
  assert.deepEqual([...kpi.matchAll(/provenance="(\w+)"/g)].map((match) => match[1]), ["ledger"]);
});

test("lo demostrativo y lo estimado nunca se etiquetan como del registro", () => {
  const workspace = read("app/dashboard/dashboard-workspace.tsx");
  const afterRevenue = workspace.slice(workspace.indexOf('label="Agentes en línea"'));
  assert.ok(!/provenance="ledger"/.test(afterRevenue), "los agentes y las aprobaciones no vienen del registro de ingresos");
  const opportunities = read("app/dashboard/dashboard-panels.tsx");
  assert.ok(!/status="ledger"/.test(opportunities), "el margen de las oportunidades es una estimación o una demostración");
  assert.match(opportunities, /status="estimated"/);
});

// --- Nada afirma que el dinero sea real (decisión del propietario, 2026-10-03) -------------------------------------
//
// El registro guarda un hecho de pago VERIFICADO, y nada más: hoy no distingue de forma estructural una operación
// simulada de una que no lo sea. Así que la etiqueta dice lo que el backend demuestra («Registro verificado») y
// ninguna pantalla puede afirmar que el dinero es real. Estas dos pruebas son el cierre de esa decisión: la primera
// impide la palabra, la segunda impide la procedencia mientras el backend no la traiga.

/** Lo que haría demostrable la afirmación: un campo de procedencia en lo que devuelven las rutas del registro. */
const STRUCTURED_ORIGIN = /\b(is_simulated|simulated|sandbox|origin|provenance|environment)\b/;

function revenueTypes(): string {
  const source = read("lib/api.ts");
  const start = source.indexOf("export type DecimalText");
  const end = source.indexOf("export interface NewOrderLine", start);
  assert.ok(start > 0 && end > start, "no se encuentran los tipos del registro en lib/api.ts");
  return source.slice(start, end);
}

test("ninguna etiqueta REAL mientras el registro no traiga una procedencia estructurada", () => {
  const hasStructuredOrigin = STRUCTURED_ORIGIN.test(revenueTypes());
  assert.equal(
    hasStructuredOrigin,
    false,
    "el registro ya trae una procedencia estructurada: revisa esta prueba y decide conscientemente qué puede afirmar la UI",
  );

  // Mientras no la traiga, «real» no puede ser una procedencia ni una etiqueta en ninguna parte del Panel.
  const badge = read("components/data-provenance-badge.tsx");
  assert.ok(!/\breal\b\s*:/.test(badge), "existe una procedencia «real» sin una fuente que la demuestre");
  assert.ok(!/label:\s*"Real"/i.test(badge), "existe una etiqueta «Real» sin una fuente que la demuestre");
  for (const file of [...dashboardFiles(), ...MEASURED]) {
    assert.ok(!/(provenance|status)="real"/.test(read(file)), `${file} etiqueta un dato como REAL sin poder demostrarlo`);
  }
});

test("los textos del Panel sobre ingresos no afirman que el dinero sea real", () => {
  const claims = /\breal(es|idad)?\b/i;
  for (const file of MEASURED) {
    assert.ok(!claims.test(read(file)), `${file} dice «real» de unas cifras que solo son hechos verificados`);
  }
  // En el Panel, la prosa de ingresos vive en estas dos constantes y en la descripción de la página.
  const workspace = read("app/dashboard/dashboard-workspace.tsx");
  const tooltips = [/const DEMO_TOOLTIP =[\s\S]*?;/, /const LEDGER_TOOLTIP =[\s\S]*?;/].map((pattern) => pattern.exec(workspace)?.[0] ?? "");
  for (const text of [...tooltips, read("app/dashboard/copy.ts")]) {
    assert.ok(text.length > 0);
    assert.ok(!claims.test(text), `un texto del Panel dice «real»: ${text.slice(0, 80)}…`);
  }
  // Y lo que sí dice: qué demuestra el backend y qué no.
  assert.match(read("lib/revenue-view.ts"), /tampoco dice si la operación/);
  assert.match(workspace, /no guarda esa procedencia/);
});

test("el Panel no presenta como medido el margen, el beneficio, los impuestos, la caja ni las comisiones", () => {
  const measured = ["app/dashboard/revenue-panels.tsx", "components/revenue-bars.tsx", "lib/revenue-query.ts"];
  const concepts = /margen|beneficio|ganancia|impuesto|\bIVA\b|\bOSS\b|comisi|\bcaja\b|\bFX\b|conversi/i;
  for (const file of measured) {
    const source = read(file).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    assert.ok(!concepts.test(source), `${file} habla de un concepto que el registro no puede demostrar`);
  }
  // En la vista solo puede aparecer dentro de la nota que dice que NO se incluye.
  const view = read("lib/revenue-view.ts")
    .replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "")
    .replace(/export const REVENUE_SCOPE_NOTE =[\s\S]*?;\n/, "");
  assert.ok(!concepts.test(view), "lib/revenue-view.ts habla de un concepto que el registro no puede demostrar");
  // Y la nota que acompaña a las cifras sí los nombra, para decir que NO están (sobre el texto ya montado, no sobre
  // cómo esté troceado en el código).
  for (const concept of ["costes", "margen", "beneficio", "impuestos", "IVA/OSS", "caja", "comisiones", "conversión de divisas"]) {
    assert.ok(REVENUE_SCOPE_NOTE.includes(concept), `la nota de alcance no dice que ${concept} queda fuera`);
  }
});

test("la vista de ingresos no suma importes: no hay aritmética con dinero", () => {
  const source = read("lib/revenue-view.ts").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
  assert.ok(!/\bparseFloat\b|\.toFixed\(|\breduce\(/.test(source), "se está sumando o redondeando dinero en la vista");
  // La única conversión a número es la de la altura de una barra.
  const conversions = [...source.matchAll(/\bNumber\(([^)]*)\)/g)].map((match) => match[1]);
  assert.deepEqual(conversions, ["bucket.revenue"]);
});

test("el selector de periodo solo navega: cambia la URL, no escribe", () => {
  // Vive en components/period-select.tsx desde el Commit 10: lo comparten el Panel y Finanzas.
  const selector = read("components/period-select.tsx");
  assert.match(selector, /router\.replace\(/);
  assert.ok(!/\bapi\./.test(selector), "el selector de periodo no llama a la API");
  const source = read("app/dashboard/revenue-panels.tsx");
  assert.ok(!/api\.(?!revenueEntries)\w+\(/.test(source), "las tarjetas del Panel solo llaman a api.revenueEntries");
});
