import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA: UNA sola semántica de los ingresos verificados y varias presentaciones (M47, Commit 3A.1).
//
//   lib/revenue-figures.ts  (núcleo puro)
//        ↓
//   /ceo (lib/ceo-kpis.ts)  ·  /dashboard y /cfo (lib/revenue-view.ts)
//
// Antes, `/ceo` tenía unas reglas (verified[], origen × moneda), `/dashboard` y `/cfo` otras (el bloque consolidado, solo EUR) y el resultado
// fueron tres defectos: USD verificado ⇒ «Sin datos», varias procedencias colapsadas y un `0,00 €` fabricado. Estas pruebas miran el código para
// impedir que vuelva a haber una transformación paralela de `verified[]`, `under_review[]`, `pending_evidence` o `non_aggregable_currencies[]`.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF, y estas pruebas miran el texto. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
const code = (file: string) => stripComments(read(file));

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules" && entry.name !== ".next") found.push(...sourceFiles(path));
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) found.push(path);
  }
  return found;
}

const ALL = ["app", "components", "lib"].flatMap(sourceFiles);

/** Los únicos módulos que pueden NOMBRAR las matrices crudas de la respuesta: el tipo, la validación del contrato y el núcleo. */
const MAY_READ_RAW = ["lib/api.ts", "lib/revenue-contract.ts", "lib/revenue-figures.ts"];

/** Los consumidores: lo que enseña el dinero de `/ceo`, `/dashboard` y `/cfo`. */
const CONSUMERS = [
  "lib/ceo-kpis.ts",
  "components/ceo/kpi-row.tsx",
  "components/ceo/revenue-kpi.tsx",
  "components/ceo/revenue-breakdown.tsx",
  "app/dashboard/dashboard-workspace.tsx",
  "app/dashboard/revenue-panels.tsx",
  "app/cfo/cfo-panels.tsx",
];

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of [...MAY_READ_RAW, ...CONSUMERS, "lib/revenue-view.ts", "lib/revenue-format.ts"]) assert.ok(ALL.includes(file), `${file} no está`);
  assert.ok(ALL.length > 100);
});

test("solo el tipo, el contrato y el núcleo nombran verified[] / under_review[] / pending_evidence / non_aggregable_currencies[] / consolidated_eur_by_origin", () => {
  const raw = /\b(under_review|pending_evidence|non_aggregable_currencies|consolidated_eur_by_origin|consolidated_eur|entries_by_provider_kind)\b/;
  const readers = ALL.filter((file) => raw.test(code(file)));
  const strangers = readers.filter((file) => !MAY_READ_RAW.includes(file));
  assert.deepEqual(strangers, [], "otro módulo lee la respuesta del registro por su cuenta: es una transformación paralela");
  assert.ok(readers.includes("lib/revenue-figures.ts") && readers.includes("lib/revenue-contract.ts"), "el núcleo y el contrato deben leerla");
  // Y `verified[]` de la respuesta (no la propiedad `verified` de otras vistas) tampoco se toca fuera de esos módulos.
  const verified = /\b(?:summary|data|settled\.data|response)\??\.verified\b/;
  assert.deepEqual(ALL.filter((file) => verified.test(code(file)) && !MAY_READ_RAW.includes(file)), []);
  assert.ok(verified.test(code("lib/revenue-figures.ts")));
});

test("el orden y el formato de las líneas existen UNA vez: en el núcleo", () => {
  for (const name of ["byCurrencyThenOrigin", "byOriginThenCurrency", "currencyRank"]) {
    const owners = ALL.filter((file) => new RegExp(`\\b${name}\\b`).test(code(file)));
    assert.deepEqual(owners, name === "byOriginThenCurrency" ? [] : ["lib/revenue-figures.ts"], `${name} vive fuera del núcleo`);
  }
  // Ningún consumidor ordena, suma ni lee el origen de una fila: pintar es otra cosa.
  for (const file of CONSUMERS) {
    const source = code(file);
    assert.doesNotMatch(source, /\.sort\(|\.reduce\(|\bparseFloat\b|\.toFixed\(|\bNumber\(/, `${file} transforma importes u orden por su cuenta`);
    assert.doesNotMatch(source, /\.provider_kind\b|\bprovider_kind\s*:|consolidated_eur/, `${file} lee la respuesta cruda`);
  }
});

test("las tres superficies consumen el núcleo y ninguna tiene su propio calculo de la cifra", () => {
  // /ceo
  const ceo = code("lib/ceo-kpis.ts");
  assert.match(ceo, /from "\.\/revenue-figures\.ts"/);
  assert.match(ceo, /revenueFigures\(settled\.data\)/);
  // /dashboard y /cfo, a través de la vista del Panel, que a su vez lee SOLO el núcleo.
  const view = code("lib/revenue-view.ts");
  assert.match(view, /from "\.\/revenue-figures\.ts"/);
  assert.match(view, /revenueFigures\(summary\)/);
  assert.match(view, /summaryFigures\(summary\)/);
  assert.match(code("app/dashboard/dashboard-workspace.tsx"), /revenueKpis\(summary\.data\)/);
  assert.match(code("app/cfo/cfo-panels.tsx"), /verifiedMetricKpis\(summary\.data\)/);
  // Y los únicos importadores del núcleo son esos dos módulos (los componentes llegan a él por ellos).
  const importers = ALL.filter((file) => /from "(?:\.\/|@\/lib\/)revenue-figures(?:\.ts)?"/.test(code(file)));
  assert.deepEqual(importers, ["lib/ceo-kpis.ts", "lib/revenue-view.ts"]);
});

test("revenue-view.ts no conserva una segunda semántica: ni el bloque consolidado, ni «Varios orígenes», ni una cifra elegida, ni aritmética con importes", () => {
  const view = code("lib/revenue-view.ts");
  assert.doesNotMatch(view, /consolidated_eur|SEVERAL_ORIGINS|ORIGIN_MULTIPLE_LABEL|eurByOrigin|under_review_outstanding/);
  assert.doesNotMatch(view, /\.reduce\(|\bparseFloat\b|\.toFixed\(/);
  // La única conversión a número de toda la vista es la altura de una barra.
  assert.deepEqual([...view.matchAll(/\bNumber\(([^)]*)\)/g)].map((m) => m[1]), ["bucket.revenue"]);
  // Una tarjeta con varias cifras dice cuántas hay y NO elige ninguna.
  assert.match(view, /`\$\{figures\.lines\.length\} cifras`/);
  assert.doesNotMatch(view, /lines\[0\]\.(?:revenue|refunds|net)\b.*lines\.length\s*>\s*1/);
});

test("el núcleo no suma, no convierte, no usa float y no lee el bloque consolidado", () => {
  const core = code("lib/revenue-figures.ts");
  assert.doesNotMatch(core, /\.reduce\(|\bparseFloat\b|\.toFixed\(|\bNumber\(/);
  assert.doesNotMatch(core, /consolidated_eur/);
  assert.doesNotMatch(core, /\bnet\s*=\s*.*(?:revenue|refunds)|revenue\s*-\s*refunds/, "el neto lo da el backend: no se recalcula");
});

test("«Ver el detalle» enlaza a tablas que existen en la MISMA página y que enseñan todas las filas", () => {
  const view = code("lib/revenue-view.ts");
  assert.match(view, /VERIFIED_TABLE_ID = "ingresos-por-moneda"/);
  assert.match(view, /OUTSIDE_TABLE_ID = "fuera-de-lo-verificado"/);
  for (const [file, id] of [
    ["app/dashboard/revenue-panels.tsx", "VERIFIED_TABLE_ID"],
    ["app/dashboard/revenue-panels.tsx", "OUTSIDE_TABLE_ID"],
    ["app/cfo/cfo-panels.tsx", "VERIFIED_TABLE_ID"],
    ["app/cfo/cfo-panels.tsx", "OUTSIDE_TABLE_ID"],
  ]) {
    assert.match(code(file), new RegExp(`<Card id=\\{${id}\\}`), `${file} no pone el id ${id} en su tabla`);
  }
  // Las tablas pintan TODAS las filas (`view.verified.map`, `underReview.map`, `pendingEvidence.lines.map`), sin recortar.
  for (const file of ["app/dashboard/revenue-panels.tsx", "app/cfo/cfo-panels.tsx"]) {
    const source = code(file);
    assert.match(source, /view\??\.verified\.map\(/);
    assert.doesNotMatch(source, /view\??\.verified\.slice\(|underReview\.slice\(|pendingEvidence\.lines\.slice\(/);
  }
  // Las tarjetas compactas llevan el enlace, y es un enlace real (teclado) con foco visible.
  for (const file of ["app/dashboard/dashboard-workspace.tsx", "app/cfo/cfo-panels.tsx"]) {
    const source = code(file);
    assert.match(source, /<a\s+href=\{`#\$\{detailId\}`\}/);
    assert.match(source, /focus-visible:ring-2/);
  }
});

test("el Panel y Finanzas siguen usando su selector de periodo sin cambios", () => {
  assert.match(code("app/dashboard/dashboard-workspace.tsx"), /<PeriodSelect days=\{days\} \/>/);
  assert.match(code("app/cfo/cfo-workspace.tsx"), /<PeriodSelect days=\{days\} label="Periodo de las finanzas" \/>/);
});
