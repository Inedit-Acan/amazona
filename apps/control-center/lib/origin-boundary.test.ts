import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// La frontera del ORIGEN del dinero en la interfaz (M46, Commit 4, ADR 0031 §11 y §12).
//
// Una convención («no deduzcas el origen del pedido») se olvida; una prueba que lee el código, no. Estas pruebas cierran
// las dos inferencias que el ADR prohibía y que existían:
//
//   1. Una pantalla de dinero que rotulaba «Simulado»/«Real» según `Order.is_simulated`.
//   2. Un margen que sumaba ingresos de orígenes distintos.
//
// y dejan una regla más: el vocabulario de pantalla del origen vive SOLO en `lib/provenance.ts`.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

/** Todos los ficheros de código de la aplicación (sin pruebas, sin dependencias, sin lo generado). */
function sourceFiles(directory = ""): string[] {
  const found: string[] = [];
  for (const name of readdirSync(join(ROOT, directory))) {
    if (["node_modules", ".next", "public", "tests", "e2e"].includes(name) || name.startsWith(".")) continue;
    const path = directory === "" ? name : `${directory}/${name}`;
    if (statSync(join(ROOT, path)).isDirectory()) {
      if (["app", "components", "lib"].includes(path.split("/")[0])) found.push(...sourceFiles(path));
    } else if (/\.tsx?$/.test(name) && !/\.test\.ts$/.test(name) && !name.endsWith(".d.ts")) {
      found.push(path);
    }
  }
  return found.sort();
}

const ALL = sourceFiles();

/** Las superficies que enseñan o calculan dinero. */
const FINANCIAL = ALL.filter((file) =>
  /^(app\/dashboard\/(revenue-panels|dashboard-workspace|copy)|app\/(cfo|operations)\/|lib\/(revenue-|cfo-|orders-view|provenance)|components\/(origin-badge|data-provenance-badge))/.test(file),
);

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of [
    "lib/provenance.ts",
    "lib/cfo-margin.ts",
    "lib/orders-view.ts",
    "lib/revenue-view.ts",
    "app/operations/operations-panels.tsx",
    "app/operations/operations-workspace.tsx",
    "app/cfo/cfo-panels.tsx",
    "app/dashboard/revenue-panels.tsx",
    "components/origin-badge.tsx",
  ]) {
    assert.ok(ALL.includes(file), `${file} no está entre los ficheros que se vigilan`);
    assert.ok(FINANCIAL.includes(file), `${file} no cuenta como superficie financiera`);
  }
  assert.ok(ALL.length > 100, "se esperaban todos los ficheros de la aplicación");
});

// --- 1. `Order.is_simulated` no decide nada financiero ------------------------------------------------------------------

test("`is_simulated` solo se lee en un sitio: el texto de contexto del pedido", () => {
  const readers = ALL.filter((file) => /\bis_simulated\b|\bisSimulated\b/.test(stripComments(read(file))));
  // El tipo (`lib/api.ts`) lo declara; `orders-view.ts` lo lee UNA vez, para el contexto. Nada más, en toda la aplicación.
  assert.deepEqual(readers, ["lib/api.ts", "lib/orders-view.ts"]);
  const reads = (stripComments(read("lib/orders-view.ts")).match(/\bis_simulated\b/g) ?? []).length;
  assert.equal(reads, 1, "orders-view.ts lee is_simulated más de una vez");
  assert.match(read("lib/orders-view.ts"), /export function orderContextText\(order: Order\): string \{\n\s+return order\.is_simulated \?/);
});

test("ninguna superficie financiera decide una etiqueta, un grupo, un margen o una fiabilidad con el contexto del pedido", () => {
  const forbidden = /\bisSimulated\b|\bis_simulated\b|\bsimulated\b\s*[:+=]/;
  for (const file of FINANCIAL.filter((candidate) => !["lib/orders-view.ts"].includes(candidate))) {
    assert.ok(!forbidden.test(stripComments(read(file))), `${file} lee el contexto del pedido en una superficie financiera`);
  }
});

test("el margen no lee el pedido para saber de dónde viene el dinero: el origen sale de las entradas del registro", () => {
  const margin = stripComments(read("lib/cfo-margin.ts"));
  assert.ok(!/\bis_simulated\b|\bsimulated\b/.test(margin));
  assert.match(margin, /entry\.provider_kind/);
  assert.ok(!/order\.payments|\.payments\b/.test(margin), "el margen no lee los cobros del pedido para decidir el origen");
});

// --- 2. Nada se suma entre orígenes -----------------------------------------------------------------------------------

test("el margen se agrega por origen con `addVerified`, que lanza si se mezclan orígenes", () => {
  const margin = stripComments(read("lib/cfo-margin.ts"));
  assert.match(margin, /import \{[^}]*\baddVerified\b[^}]*\} from "\.\/provenance\.ts"/);
  assert.match(margin, /rows\.reduce\(\(sum, row\) => addVerified\(sum, row\.revenue\), zero\)/);
  assert.match(margin, /rows\.reduce\(\(sum, row\) => addVerified\(sum, row\.refunds\), zero\)/);
  // La clave de la agrupación incluye el origen, y no hay ninguna agregación que recorra todos los pedidos sin él.
  assert.match(margin, /byOrigin: Map<Origin, OriginTotals>/);
  assert.ok(!/orders\.reduce|totals\.values\(\)\.reduce/.test(margin));
});

test("el resumen del margen no tiene ninguna cifra a nivel global, solo por origen", () => {
  const margin = read("lib/cfo-margin.ts");
  const summary = margin.slice(margin.indexOf("export interface MarginSummary"), margin.indexOf("interface OriginTotals"));
  for (const field of ["margin:", "revenue:", "refunds:", "net:", "cost:", "coverage:"]) {
    assert.ok(!summary.includes(`  ${field}`), `MarginSummary tiene «${field}», una cifra que cruzaría orígenes`);
  }
  assert.match(summary, /origins: OriginMargin\[\]/);
});

test("el dinero de Operaciones se agrupa por origen: no hay `addTo` sobre todos los cobros", () => {
  const source = stripComments(read("lib/orders-view.ts"));
  const kpis = source.slice(source.indexOf("export function orderKpis"), source.indexOf("export function orderOrigin"));
  assert.ok(!/\baddTo\(captured|\baddTo\(refunded/.test(kpis), "orderKpis suma sin origen");
  assert.match(kpis, /noteMoney\(captured, payment\.provider_kind, payment\.captured_amount\)/);
  assert.match(kpis, /noteMoney\(refunded, payment\.provider_kind, payment\.refunded_amount\)/);
});

test("ninguna vista suma los importes de los hechos por encima del origen", () => {
  const view = stripComments(read("lib/revenue-view.ts"));
  assert.ok(!/\badd\(|\bsubtract\(|\.reduce\(\s*\(/.test(view), "revenue-view.ts hace aritmética con importes");
  assert.ok(!/consolidated_eur\b(?!_by_origin)/.test(view), "revenue-view.ts vuelve a leer el consolidado antiguo");
});

// --- 3. El vocabulario de origen vive en un solo sitio ---------------------------------------------------------------------

test("las etiquetas de origen solo se escriben en lib/provenance.ts", () => {
  const labels = ["Entorno de pruebas", "Proveedor real", "Varios orígenes", "Sin datos de origen", "Sin cobro"];
  for (const file of ALL.filter((candidate) => candidate !== "lib/provenance.ts")) {
    const code = stripComments(read(file));
    for (const label of labels) {
      assert.ok(!code.includes(`"${label}"`) && !code.includes(`'${label}'`) && !code.includes(`\`${label}\``), `${file} escribe su propia etiqueta «${label}»`);
    }
  }
  // Y nadie construye su propio mapa de origen → texto.
  for (const file of ALL.filter((candidate) => /\.tsx$/.test(candidate))) {
    assert.ok(!/\bmock:\s*["'`]|\bsandbox:\s*["'`]/.test(stripComments(read(file))), `${file} define su propio texto por origen`);
  }
});

test("un origen se pinta siempre con `OriginBadge` o con el nombre de la fuente única, nunca con el valor crudo", () => {
  for (const file of ALL.filter((candidate) => /\.tsx$/.test(candidate))) {
    const code = stripComments(read(file));
    assert.ok(
      !/>\s*\{\s*[\w.?]*\.(providerKind|provider_kind)\s*\}/.test(code),
      `${file} pinta un provider_kind crudo como texto`,
    );
    assert.ok(!/\{\s*[\w.?]*\.(providerKind|provider_kind)\s*\}\s*·/.test(code), `${file} concatena un provider_kind crudo`);
  }
  assert.match(read("components/origin-badge.tsx"), /originLabel\(summary\)/);
  assert.match(read("components/origin-badge.tsx"), /originMeaning\(summary\)/);
});

test("el origen nunca se lee de la configuración, del entorno ni de un nombre", () => {
  for (const file of FINANCIAL) {
    const code = stripComments(read(file));
    assert.ok(!/process\.env|NEXT_PUBLIC_|payments_provider|\.provider\s*===|\.provider\.(startsWith|includes)/.test(code), `${file} decide algo con la configuración o el nombre del proveedor`);
  }
});

// --- 4. Ningún texto afirma más de lo que se sabe -----------------------------------------------------------------------------

test("ningún texto financiero dice «real» fuera de la definición del origen, ni afirma dinero real, beneficio real o ingresos reales", () => {
  const claims = /\breal(es|idad|mente)?\b/i;
  for (const file of FINANCIAL.filter((candidate) => candidate !== "lib/provenance.ts")) {
    // Los comentarios pueden nombrar el vocabulario; el código y los textos no dicen «real».
    const lines = stripComments(read(file))
      .split("\n")
      .filter((line) => claims.test(line));
    assert.deepEqual(lines, [], `${file} dice «real»: ${lines.join(" | ")}`);
  }
  const misleading = /dinero real|ingresos? reales?|beneficio real|realmente cobrad|datos reales|dinero que se movi/i;
  for (const file of FINANCIAL) {
    assert.ok(!misleading.test(stripComments(read(file))), `${file} afirma más de lo que el backend demuestra`);
  }
});

test("las etiquetas «Real» y «Simulado» como rótulo solo salen de la fuente única", () => {
  for (const file of FINANCIAL.filter((candidate) => candidate !== "lib/provenance.ts")) {
    const code = stripComments(read(file));
    assert.ok(!/["'`>]\s*Real\s*["'`<]/.test(code), `${file} rotula «Real»`);
    assert.ok(!/["'`>]\s*Simulado\s*["'`<]/.test(code), `${file} rotula «Simulado»`);
  }
  assert.ok(!/"Real"/.test(stripComments(read("lib/provenance.ts"))), "ni siquiera la fuente única usa el rótulo «Real» a secas");
});

test("lo que es PLAN o DEMO sigue etiquetado como tal y no se mezcla con un origen", () => {
  const provenance = read("lib/provenance.ts");
  assert.match(provenance, /planned: "Proyección \(PLAN\)"/);
  assert.match(provenance, /demo: "Demostración"/);
  assert.ok(!/ORIGIN_LABEL[\s\S]{0,400}PLAN/.test(provenance.slice(provenance.indexOf("export const ORIGIN_LABEL"), provenance.indexOf("export const ORIGIN_MULTIPLE_LABEL"))));
  // El eje del origen no toca los tipos de lo declarado, lo proyectado ni lo inventado.
  assert.match(provenance, /export type Declared<T> = Tagged<"declared", T>;/);
  assert.match(provenance, /export type Planned<T> = Tagged<"planned", T>;/);
  assert.match(provenance, /export type Demo<T> = Tagged<"demo", T>;/);
});

test("la ruta relativa de cada fichero vigilado existe (la prueba no pasa en vacío)", () => {
  for (const file of FINANCIAL) assert.ok(statSync(join(ROOT, file)).isFile(), relative(ROOT, join(ROOT, file)));
  assert.ok(FINANCIAL.length >= 15, `solo ${FINANCIAL.length} superficies financieras vigiladas`);
});
