import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// La frontera del presupuesto operativo (M47). Mira el código mismo, como las demás fronteras del Control Center: una regla que se
// cumple hoy por casualidad no sirve si mañana alguien puede saltársela sin que nada se queje.
//
//   1. Hay UNA fuente: `GET /api/budget`, leída por `readBudget`, y `/ceo` y `/cfo` enseñan la MISMA vista.
//   2. Nada está hardcodeado: ni el techo de la prueba (1,00), ni una moneda por defecto, ni un presupuesto de demostración.
//   3. Un error de lectura no puede acabar en un cero, y el dinero no se calcula con `float`.
//   4. Lo gastado no entra en la cuenta del disponible, y el presupuesto no se rotula como caja.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relative = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (!["node_modules", ".next"].includes(entry.name)) found.push(...sourceFiles(relative));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      found.push(relative);
    }
  }
  return found;
}

const ALL = ["app", "components", "lib"].flatMap(sourceFiles);

const VIEW = "lib/budget-view.ts";
const PARTS = "components/budget-parts.tsx";
const CEO_BLOCK = "components/ceo/budget-block.tsx";
const CFO_SECTION = "app/cfo/budget-section.tsx";
const CFO_PAGE = "app/cfo/page.tsx";
const CFO_WORKSPACE = "app/cfo/cfo-workspace.tsx";
const CEO_PAGE = "app/ceo/page.tsx";
const BUDGET_FILES = [VIEW, PARTS, CEO_BLOCK, CFO_SECTION];

test("1 · UNA fuente: solo `lib/api.ts` y la lectura de `lib/budget-view.ts` conocen la ruta y el método del presupuesto", () => {
  const knowing = ALL.filter((file) => /\bgetBudget\b|\/api\/budget\b/.test(code(file))).sort();
  assert.deepEqual(knowing, ["lib/api.ts", VIEW].sort());
});

test("1b · la lectura es un GET sin cuerpo ni método: el cliente no puede escribir el presupuesto", () => {
  const line = read("lib/api.ts")
    .split("\n")
    .find((row) => row.includes("getBudget:"));
  assert.ok(line, "falta getBudget en el cliente de la API");
  assert.match(line, /getBudget:\s*\(\)\s*=>\s*request<BudgetRead>\("\/api\/budget"\)\s*,?\s*$/);
  assert.doesNotMatch(line, /method|body|POST|PUT|PATCH|DELETE|idempot/i);
});

test("1c · `/ceo` y `/cfo` leen con la MISMA función, una vez cada una, y reciben la misma vista", () => {
  const ceo = code(CEO_BLOCK);
  const cfo = code(CFO_PAGE);
  for (const [name, source] of [["ceo", ceo], ["cfo", cfo]] as const) {
    assert.match(source, /import\s*\{[^}]*\breadBudget\b[^}]*\}\s*from\s*"@\/lib\/budget-view"/, `${name} no importa readBudget de la vista compartida`);
    assert.equal((source.match(/\breadBudget\(api\)/g) ?? []).length, 1, `${name} no lee el presupuesto exactamente una vez`);
  }
  // La pantalla de Finanzas recibe la vista ya hecha: el componente de cliente no lee nada.
  assert.match(code(CFO_WORKSPACE), /<BudgetSection view=\{budget\}\s*\/>/);
  assert.doesNotMatch(code(CFO_WORKSPACE), /readBudget|getBudget/);
});

test("1d · las dos pantallas pintan con las MISMAS piezas, y ninguna lee otra fuente de presupuesto (ni el informe del agente CFO, ni demostración)", () => {
  for (const file of [CEO_BLOCK, CFO_SECTION]) {
    const source = code(file);
    assert.match(source, /from\s*"@\/components\/budget-parts"/, `${file} no usa las piezas compartidas`);
    assert.doesNotMatch(source, /total_budget_hard_limit|budget_utilization|total_reserved|total_committed|listCFORuns|CFOReport/, `${file} lee el presupuesto del informe del agente`);
  }
  for (const file of BUDGET_FILES) {
    assert.doesNotMatch(code(file), /lib\/demo|from\s*"\.\/demo|@\/lib\/demo|\bDEMO\b|demoBudget|MOCK_/i, `${file} usa datos de demostración`);
  }
});

test("1f · Finanzas enseña el presupuesto también cuando falla la lectura de productos: con su propio estado, no en blanco", () => {
  const page = code(CFO_PAGE);
  const errorBranch = page.slice(page.indexOf("if (error) {"), page.indexOf("return (", page.indexOf("if (error) {") + 12) + 400);
  assert.match(errorBranch, /<BudgetSection view=\{budget\} \/>/);
});

test("1e · `/ceo` y `/cfo` incluyen el bloque, y el de `/ceo` va en un límite de Suspense (sin cifra ni cero mientras lee)", () => {
  assert.match(code(CEO_PAGE), /<Suspense fallback=\{<BudgetSkeleton \/>\}>\s*<BudgetBlock \/>\s*<\/Suspense>/);
  assert.match(code(CFO_PAGE), /budget=\{budget\}/);
});

test("2 · nada hardcodeado: ni el techo de la prueba, ni una moneda por defecto, ni cifras con céntimos", () => {
  for (const file of BUDGET_FILES) {
    const source = code(file);
    assert.doesNotMatch(source, /\bEUR\b|€/, `${file} da una moneda por supuesta`);
    assert.doesNotMatch(source, /\b\d+[.,]\d{2}\b/, `${file} lleva un importe escrito a mano`);
    assert.doesNotMatch(source, /\bhard_limit\s*[:=]\s*["']?\d/, `${file} fija un techo`);
  }
});

test("2b · la moneda solo se da por buena con su procedencia contractual", () => {
  const view = code(VIEW);
  assert.match(view, /source === "accounting_currency"/);
  assert.match(view, /CURRENCY_CODE\.test\(currency\)/);
});

test("3 · un error de lectura no tiene forma de convertirse en un cero, y el dinero no se calcula con float", () => {
  for (const file of BUDGET_FILES) {
    const source = code(file);
    assert.doesNotMatch(source, /\.catch\s*\(|\?\?\s*0\b|\|\|\s*0\b|\bparseFloat\b|\.toFixed\(|\.reduce\(|\bparseInt\b/, `${file} cuenta un error como cero o usa float`);
    assert.doesNotMatch(source, /catch\s*(?:\([^)]*\))?\s*\{[^{}]*\b(?:return|=)\s*(?:\[\]|null|undefined|0|\{\}|"")/, `${file} traga un error`);
  }
  // `Number(` solo existe donde no hay dinero: el porcentaje (que sale de enteros). Ni los componentes ni nada más lo llaman.
  assert.equal((code(VIEW).match(/\bNumber\(/g) ?? []).length, 1, "Number( solo en el porcentaje");
  for (const file of [PARTS, CEO_BLOCK, CFO_SECTION]) assert.doesNotMatch(code(file), /\bNumber\(/, file);
});

test("4 · lo gastado no entra en la cuenta del disponible, ni en la del uso", () => {
  const view = code(VIEW);
  assert.match(view, /const used = add\(reserved, committed\);/);
  assert.match(view, /subtract\(hard, used\)/);
  assert.doesNotMatch(view, /(?:add|subtract)\([^)]*\bspent\b/, "lo gastado se está sumando o restando");
});

test("4b · los textos de estado salen de la vista: los componentes no escriben «Agotado», «Inconsistente» ni «No hay presupuesto»", () => {
  for (const file of [PARTS, CEO_BLOCK, CFO_SECTION]) {
    assert.doesNotMatch(code(file), /Agotado|Inconsistente|No hay presupuesto autorizado|Parcialmente usado/, `${file} escribe un estado por su cuenta`);
  }
});

test("4c · el presupuesto se rotula «Presupuesto operativo» y nunca como caja", () => {
  for (const file of BUDGET_FILES) assert.doesNotMatch(code(file), /Cash disponible|Caja disponible|Saldo disponible/, file);
  assert.match(code(VIEW), /BUDGET_TITLE = "Presupuesto operativo"/);
  assert.match(read(CEO_BLOCK) + read(CFO_SECTION), /BUDGET_TITLE/);
  assert.match(code(VIEW), /BUDGET_SCOPE_NOTE = "[^"]*no es caja[^"]*ingresos/);
});

test("4d · «Agotado» solo se pinta con un presupuesto leído: el aviso de error, vacío o sin leer no lleva estado", () => {
  const parts = code(PARTS);
  const notice = parts.slice(parts.indexOf("export function BudgetNotice"), parts.indexOf("export function BudgetStat"));
  assert.doesNotMatch(notice, /statusLabel|BudgetStatusChip|remaining|hardLimit|committed/);
  assert.match(code(CEO_BLOCK), /view\.kind === "loaded" \? <BudgetStatusChip view=\{view\} \/> : null/);
});

test("5 · /status no se convierte en un panel financiero", () => {
  for (const file of ALL.filter((name) => name.startsWith("app/status/") || name === "lib/status-reads.ts")) {
    assert.doesNotMatch(code(file), /readBudget|budget-view|getBudget/, file);
  }
});
