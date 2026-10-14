import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// La frontera de lectura del Panel (M46, Commit 6). Mira el código mismo, como las demás fronteras del Control Center: una
// regla que se cumple hoy por casualidad no sirve si mañana alguien puede saltársela sin que nada se queje.
//
//   Qué gobierna: las capas de LECTURA del Panel (`app/dashboard/*`, `lib/dashboard-*`, `lib/read-state.ts`, los dos
//   componentes de error). Ahí no puede existir ninguna forma de convertir un error de lectura en un dato vacío.
//   Qué NO gobierna: las demás pantallas. Tienen la misma deuda (ver `REMAINING_SILENT_READS`), con un trinquete que solo
//   permite que mengüe: no se rompe ninguna, pero no puede crecer ni esconderse.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relative = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (!["node_modules", "demo", ".next"].includes(entry.name)) found.push(...sourceFiles(relative));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      found.push(relative);
    }
  }
  return found;
}

const ALL = ["app", "components", "lib"].flatMap(sourceFiles);

/** Las capas de lectura que este commit gobierna. */
const GOVERNED = [
  "app/dashboard/page.tsx",
  "app/dashboard/dashboard-workspace.tsx",
  "app/dashboard/dashboard-panels.tsx",
  "lib/dashboard-reads.ts",
  "lib/dashboard-view.ts",
  "lib/read-state.ts",
  "components/read-error-notice.tsx",
  "components/retry-button.tsx",
];

const EMPTY_VALUE = String.raw`(?:\[\]|null|undefined|0|\{\}|""|false)`;

/** `.catch(() => [])`, `.catch((): X[] => [])`, `.catch(() => [] as X[])`, `.catch(() => null)`… */
const SILENT_CATCH = new RegExp(String.raw`\.catch\(\s*\(\s*\)\s*(?::\s*[^=]+?)?=>\s*(?:\[\]|null|undefined|0|\{\}|"")(?:\s+as\s+[^)]+)?\s*\)`, "g");
/** `catch (e) { return [] }` / `catch { return null }`… */
const CATCH_RETURNING_EMPTY = new RegExp(String.raw`catch\s*(?:\([^)]*\))?\s*\{[^{}]*\breturn\s+${EMPTY_VALUE}\s*;?\s*\}`, "g");
/** `catch {}` y `catch (e) {}`: un error que se traga sin más. */
const EMPTY_CATCH = /catch\s*(?:\([^)]*\))?\s*\{\s*\}/g;
/** `try { … } catch { x = [] }`: se asigna un vacío dentro del catch. */
const CATCH_ASSIGNING_EMPTY = new RegExp(String.raw`catch\s*(?:\([^)]*\))?\s*\{[^{}]*=\s*${EMPTY_VALUE}\s*;?[^{}]*\}`, "g");

test("1 · en las capas de lectura del Panel no existe NINGUNA forma de convertir un error en un dato vacío", () => {
  for (const file of GOVERNED) {
    const source = code(file);
    assert.deepEqual(source.match(SILENT_CATCH) ?? [], [], `${file}: .catch(() => <vacío>)`);
    assert.deepEqual(source.match(CATCH_RETURNING_EMPTY) ?? [], [], `${file}: catch { return <vacío> }`);
    assert.deepEqual(source.match(EMPTY_CATCH) ?? [], [], `${file}: catch vacío`);
    assert.deepEqual(source.match(CATCH_ASSIGNING_EMPTY) ?? [], [], `${file}: catch { x = <vacío> }`);
    assert.ok(!/\.catch\(/.test(source), `${file}: usa .catch(…): las lecturas pasan por readList / settle`);
  }
});

test("2 · el Panel lee SOLO por `readList` / `settle`: ninguna llamada a la API queda fuera", () => {
  const page = code("app/dashboard/page.tsx");
  assert.match(page, /readDashboard\(api\)/, "la página lee con readDashboard");
  const direct = [...page.matchAll(/\bapi\.\w+\(/g)];
  assert.ok(direct.length > 0);
  for (const match of direct) {
    const before = page.slice(Math.max(0, (match.index ?? 0) - 40), match.index);
    assert.match(before, /settle\(\s*\(\)\s*=>\s*$/, `${match[0]} se llama fuera de settle`);
  }

  const reads = code("lib/dashboard-reads.ts");
  const calls = [...reads.matchAll(/\bsource\.\w+\(/g)];
  assert.equal(calls.length, 10, "las diez lecturas del Panel: el catálogo, las cuatro globales y las cinco por producto");
  for (const match of calls) {
    const before = reads.slice(Math.max(0, (match.index ?? 0) - 30), match.index);
    assert.match(before, /readList\(\s*\(\)\s*=>\s*$/, `${match[0]} se llama fuera de readList`);
  }
  assert.ok(!/\bsource\.(?!list)\w+\(/.test(reads), "el Panel solo lee: ninguna llamada de escritura");
  // Y el CONTRATO de la fuente tampoco puede declarar una escritura (un método que nadie llama hoy es la puerta de mañana).
  const contract = reads.slice(reads.indexOf("interface DashboardSource"), reads.indexOf("}", reads.indexOf("interface DashboardSource")));
  const members = [...contract.matchAll(/^\s*(\w+)\(/gm)].map((match) => match[1]);
  assert.equal(members.length, 10);
  assert.ok(members.every((name) => name.startsWith("list")), `DashboardSource declara algo que no es una lectura: ${members.join(", ")}`);
});

test("3 · `ReadState` tiene exactamente cuatro estados y el Panel recibe cada lectura con su estado, no una lista", () => {
  const state = code("lib/read-state.ts");
  const kinds = [...state.matchAll(/\{\s*kind:\s*"(\w+)"/g)].map((match) => match[1]).slice(0, 4);
  assert.deepEqual(kinds, ["loaded", "empty", "unread", "error"]);

  const reads = code("lib/dashboard-reads.ts");
  for (const field of ["products", "agents", "executions", "approvals", "reviews"]) {
    assert.match(reads, new RegExp(String.raw`\b${field}:\s*ReadState<`), `${field} no es un ReadState`);
  }
  for (const field of ["quotes", "economics", "legal", "storefronts", "campaigns"]) {
    assert.match(reads, new RegExp(String.raw`\b${field}:\s*ReadState<`), `${field} no es un ReadState`);
  }
  const workspace = code("app/dashboard/dashboard-workspace.tsx");
  assert.match(workspace, /reads:\s*DashboardReads/);
  assert.ok(!/\bagents:\s*Agent\[\]|\bexecutions:\s*AgentExecution\[\]|\bapprovals:\s*Approval\[\]/.test(workspace), "el cliente recibe listas, no estados");
});

test("4 · el estado de error y el vacío NO comparten presentación: error ⇒ aviso con reintento; vacío ⇒ estado vacío", () => {
  const panels = code("app/dashboard/dashboard-panels.tsx");
  assert.equal((panels.match(/<ReadErrorNotice/g) ?? []).length, 3, "las tres tarjetas dicen cuando su lectura falló");
  assert.equal((panels.match(/view\.kind === "unavailable"/g) ?? []).length, 3);
  for (const empty of ["no-agents", "no-catalog"]) assert.match(panels, new RegExp(String.raw`"${empty}"`));
  // El texto de «sin datos» nunca se escribe en una rama de error.
  assert.ok(!/Sin datos|No hay /.test(panels), "las tarjetas del Panel no usan «Sin datos» / «No hay…»");

  const notice = code("components/read-error-notice.tsx");
  assert.match(notice, /variant="destructive"/);
  assert.match(notice, /<RetryButton/);
  // El aviso DICE el motivo: el título y el mensaje llegan a la pantalla (un error que no se ve es un error tragado).
  assert.match(notice, /<AlertTitle>\{title\}<\/AlertTitle>/, "el título del aviso no se pinta");
  assert.match(notice, /<p>\{message\}<\/p>/, "el mensaje del aviso no se pinta");
  assert.match(notice, /retry = true/, "el reintento está disponible por defecto");
});

test("5 · un error no se convierte en demostración: la demo solo entra con el log VÁLIDO y vacío", () => {
  const view = code("lib/dashboard-view.ts");
  const activity = view.slice(view.indexOf("export function activityView("), view.indexOf("// --- Decisiones necesarias", view.indexOf("export function activityView(")));
  assert.ok(activity.includes("failedSources"), "activityView comprueba las lecturas fallidas");
  assert.ok(
    activity.indexOf("failedSources") < activity.indexOf("demoExecutions("),
    "la demostración se decide DESPUÉS de descartar los errores",
  );
  assert.match(activity, /usingDemoRuns\s*=\s*executions\.kind === "empty"/);

  const workspace = code("app/dashboard/dashboard-workspace.tsx");
  assert.match(workspace, /reads\.agents\.kind === "loaded" \|\| reads\.agents\.kind === "empty"/, "sin agentes leídos no se construyen solicitudes de demostración");
});

test("6 · el reintento es manual y de UNA petición: sin temporizadores, sin bucles, sin efectos", () => {
  const retry = code("components/retry-button.tsx");
  assert.equal((retry.match(/router\.refresh\(\)/g) ?? []).length, 1);
  assert.ok(!/setInterval|setTimeout|requestAnimationFrame|useEffect|while\s*\(|for\s*\(/.test(retry), "el botón no reintenta por su cuenta");
  assert.match(retry, /disabled=\{pending\}/, "mientras reintenta no admite otro clic");

  for (const file of ["app/dashboard/page.tsx", "app/dashboard/dashboard-workspace.tsx", "app/dashboard/dashboard-panels.tsx", "lib/dashboard-reads.ts"]) {
    assert.ok(!/setInterval|setTimeout|router\.refresh|revalidate|useEffect/.test(code(file)), `${file}: reintento automático`);
  }
});

test("7 · al usuario no le llega nada técnico: ni el mensaje crudo del error, ni su estado, ni su detalle", () => {
  for (const file of [...GOVERNED, "app/dashboard/revenue-panels.tsx"]) {
    const source = code(file);
    assert.ok(!/\berr(?:or)?\.(?:message|detail|status)\b[^;\n]*(?:<|\{)/.test(source) || file === "lib/dashboard-view.ts", file);
    assert.ok(!/ApiErrorAlert/.test(source), `${file}: el Panel ya no usa el aviso con el mensaje crudo del error`);
    assert.ok(!/String\(\s*err(?:or)?\s*\)|JSON\.stringify\(\s*err/.test(source), `${file}: serializa un error para enseñarlo`);
  }
  // `revenue-panels` solo pasa el ESTADO al generador de texto: el detalle y el mensaje del error no se usan.
  const revenue = code("app/dashboard/revenue-panels.tsx");
  assert.ok(!/err\.detail|err\.message/.test(revenue), "revenue-panels muestra el detalle del error");
});

test("8 · ningún valor ausente se pinta como cero en las capas de lectura", () => {
  for (const file of GOVERNED) {
    const source = code(file);
    // La única excepción es la clave de ORDEN de `activityRows` (`lastActivityAt ?? 0`): ordena, no se enseña.
    const allowedZeros = file === "lib/dashboard-view.ts" ? 2 : 0;
    assert.equal((source.match(/\?\?\s*0\b(?!\.)/g) ?? []).length, allowedZeros, `${file}: \`?? 0\``);
    assert.ok(!/\|\|\s*0\b(?!\.)/.test(source), `${file}: \`|| 0\``);
  }
  const view = code("lib/dashboard-view.ts");
  const sort = view.slice(view.indexOf("export function activityRows("), view.indexOf("// --- Decisiones necesarias"));
  assert.equal((sort.match(/\?\?\s*0\b(?!\.)/g) ?? []).length, 2, "los dos `?? 0` permitidos están en la comparación de activityRows");
});

test("9 · la lectura de productos ya no sustituye toda la página por un aviso técnico", () => {
  const page = code("app/dashboard/page.tsx");
  assert.ok(!/PageHeader|ApiErrorAlert|error\s*=/.test(page), "la página no decide ningún error global: cada tarjeta dice el suyo");
});

// --- Trinquete de las demás pantallas -------------------------------------------------------------------------------

/** Lecturas que TODAVÍA tragan su error fuera del Panel. Son deuda conocida de M46 (Commit 6 cerró las 9 del Panel): este
 * trinquete solo deja que mengüe. Añadir una nueva —en una pantalla de la lista o en cualquier otra— o dejar de contar una
 * sin bajar su número rompe la prueba. */
const REMAINING_SILENT_READS: Record<string, number> = {
  "app/agents/page.tsx": 1,
  "app/approvals/page.tsx": 8,
  "app/audit/page.tsx": 2,
  "app/economics/page.tsx": 3,
  "app/legal/page.tsx": 3,
  "app/operations/page.tsx": 1,
  "app/research/page.tsx": 2,
  "app/sourcing/page.tsx": 1,
  "app/status/page.tsx": 6,
  // No son listas de negocio: `null` = «sin sesión» (auth) y un `undefined` de mejor esfuerzo (interruptor de emergencia).
  "components/kill-switch-control.tsx": 1,
  "lib/auth-server.ts": 2,
};

test("10 · trinquete: las lecturas que aún tragan su error fuera del Panel no pueden crecer ni esconderse", () => {
  for (const file of ALL) {
    const count = (code(file).match(SILENT_CATCH) ?? []).length;
    const allowed = REMAINING_SILENT_READS[file] ?? 0;
    assert.ok(count <= allowed, `${file}: ${count} lecturas tragan su error (se permiten ${allowed}). Usa readList / settle y anota el fallo.`);
    assert.ok(count >= allowed, `${file}: ahora hay ${count}: baja REMAINING_SILENT_READS a ${count} para que el trinquete no retroceda`);
  }
  const total = Object.values(REMAINING_SILENT_READS).reduce((sum, count) => sum + count, 0);
  assert.equal(total, 30, "27 lecturas de otras pantallas + 3 de otra naturaleza (el grafo salió en M47 · Commit 1 y /ceo en el Commit 2)");
  for (const file of GOVERNED) assert.equal(REMAINING_SILENT_READS[file] ?? 0, 0, `${file} está gobernado: cero`);
});
