import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { AuditEntry, Decision, Project, Task } from "./api.ts";
import { projectCard } from "./projects-view.ts";
import { NO_DATA, settle, UNREAD } from "./revenue-view.ts";

// La frontera de M45 que cruza las TRES pantallas (Commit 12): Panel, Finanzas y Proyectos.
//
// Cada pantalla tiene su propia prueba de frontera (`dashboard-revenue-boundary`, `cfo-boundary`,
// `projects-boundary`). Esta fija lo que ninguna de las tres puede fijar sola: que lo que está prohibido en una **no
// reaparece en otra**, y que un error de lectura **no se convierte en dato** en ninguna. Mira el código mismo, igual
// que las demás: una regla que se cumple hoy por casualidad no sirve si mañana alguien puede saltársela sin que nada
// se queje.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relative = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules" && entry.name !== "demo" && entry.name !== ".next") found.push(...sourceFiles(relative));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      found.push(relative);
    }
  }
  return found;
}

const ALL = ["app", "components", "lib"].flatMap(sourceFiles);
const SCREENS = {
  dashboard: ALL.filter((file) => file.startsWith("app/dashboard/")),
  cfo: [...ALL.filter((file) => file.startsWith("app/cfo/")), "lib/cfo-margin.ts", "lib/cfo-plan.ts", "lib/cfo-verdict.ts"],
  projects: [...ALL.filter((file) => file.startsWith("app/projects/")), "lib/projects-view.ts", "lib/projects.ts"],
};

// --- 1 · Lo que se retiró no vuelve, en ninguna parte ---------------------------------------------------------------

test("1 · buildOrders solo vive en Operaciones; realProfit, capitalExposed y demoProjects no existen en ninguna parte", () => {
  const using = (identifier: RegExp) => ALL.filter((file) => identifier.test(stripComments(read(file))));
  assert.deepEqual(using(/\bbuildOrders\b/), ["lib/operations-view.ts"], "otra pieza fabrica pedidos generados");
  for (const gone of [/\brealProfit\b/, /\bcapitalExposed\b/, /\bdemoProjects\b/, /\bDEMO_SUPPLIER_ADVANCE\b/, /\bDEMO_PROJECTS\b/, /\bDEMO_CLOSED_PROJECTS\b/]) {
    assert.deepEqual(using(gone), [], `${gone} ha vuelto`);
  }
});

test("1b · ninguna de las tres pantallas importa un generador de datos de demostración en su vista de dinero", () => {
  const importsDemo = /from\s+"(@\/lib\/demo\/[^"]+|\.{1,2}\/(?:\.{2}\/)*demo\/[^"]+)"/;
  for (const file of [...SCREENS.cfo, ...SCREENS.projects, "app/dashboard/revenue-panels.tsx", "lib/revenue-view.ts"]) {
    assert.ok(!importsDemo.test(read(file)), `${file} importa lib/demo`);
  }
});

// --- 2 · Ninguna pantalla llama «real» a lo que no lo demuestra -----------------------------------------------------

test("2 · ninguna de las tres pantallas habla de dinero «real», de «beneficio real» ni de «ingresos reales»", () => {
  for (const [name, files] of Object.entries(SCREENS)) {
    for (const file of files) {
      const code = stripComments(read(file));
      // Negar que algo sea real («no tiene ventas ni costes reales») es decir la verdad, no llamar «real» a una cifra.
      assert.ok(!/(?<!\bni\s)(?<!\bno\s)(beneficio|ingresos?|ventas?|dinero)\s+reales?/i.test(code), `${name}: ${file} llama «real» a una cifra`);
      assert.ok(!/status="real"|"REAL"/.test(code), `${name}: ${file} etiqueta algo como REAL`);
    }
  }
});

// --- 3 · PLAN y DEMO no se visten de hecho verificado --------------------------------------------------------------

test("3 · una tarjeta que enseña una proyección PLAN nunca lleva solo una etiqueta de hecho verificado", () => {
  const verifiedLabel = /status="(ledger|verified)"/;
  const showsProjection = /\b(projected|planned|plannedMonthlyProfit|PlanCard|plan\.rows|perOrder|perUnit)\b/;
  for (const file of [...SCREENS.cfo, ...SCREENS.projects, ...SCREENS.dashboard]) {
    const lines = stripComments(read(file)).split("\n");
    lines.forEach((line, index) => {
      if (!verifiedLabel.test(line)) return;
      // La etiqueta mira a su tarjeta, no a la línea: se mira la tarjeta entera, desde su `<Card` hasta la siguiente.
      const start = lines.slice(0, index + 1).findLastIndex((candidate) => /<Card[\s>]/.test(candidate));
      const end = lines.findIndex(
        (candidate, k) => k > index && (/<Card[\s>]/.test(candidate) || /^export function /.test(candidate)),
      );
      const card = lines.slice(Math.max(start, 0), end === -1 ? lines.length : end).join("\n");
      if (!showsProjection.test(card)) return;
      assert.ok(
        /status="planned"/.test(card),
        `${file}:${index + 1}: una tarjeta enseña una proyección y solo se declara verificada: tiene que declararse PLAN también`,
      );
    });
  }
});

// --- 4 · «Sin datos» no es cero, en ninguna pantalla ---------------------------------------------------------------

test("4 · una cifra ausente no se pinta como cero: ni `?? 0` ni `|| 0` en las tres pantallas", () => {
  for (const [name, files] of Object.entries(SCREENS)) {
    for (const file of files) {
      const code = stripComments(read(file));
      assert.ok(!/\?\?\s*0\b(?!\.)/.test(code), `${name}: ${file} convierte un valor ausente en cero con \`?? 0\``);
      assert.ok(!/\|\|\s*0\b(?!\.)/.test(code), `${name}: ${file} convierte un valor ausente en cero con \`|| 0\``);
    }
  }
});

// --- 5 · Un error de lectura no es un dato -------------------------------------------------------------------------

/** `.catch(() => [])`, `.catch((): X[] => [])`, `.catch(() => null)`…: una lectura que falla y se vuelve un dato vacío. */
const SILENT = /\.catch\(\s*\(\s*\)\s*(?::\s*[^=]+)?=>\s*(\[\]|null|undefined|0|\{\}|"")\s*\)/g;

/** Lecturas que hoy tragan su error y NO son dinero: el panel operativo y el catálogo del Panel (agentes, ejecuciones,
 * aprobaciones, revisiones y, por producto, proveedores, economía, legal, tienda y campañas). Es una DEUDA conocida
 * (pasa a M46), y el trinquete solo permite que mengüe: añadir una nueva, o dejar de contarla sin bajar el número,
 * rompe la prueba. */
const LEGACY_SILENT_READS: Record<string, number> = {
  "app/dashboard/page.tsx": 9,
};

const silentReads = (file: string) => [...stripComments(read(file)).matchAll(SILENT)].map((match) => match[0]);

test("5 · Finanzas y Proyectos distinguen «no se pudo leer»: ninguna de sus lecturas convierte su error en un vacío", () => {
  for (const file of ["app/cfo/page.tsx", "app/projects/page.tsx"]) {
    assert.deepEqual(silentReads(file), [], `${file} traga un error de lectura`);
    assert.ok(/unread|Unread/.test(stripComments(read(file))), `${file} no anota lo que no se pudo leer`);
  }
});

test("5b · el trinquete de lecturas silenciosas solo mengua", () => {
  for (const file of ["app/cfo/page.tsx", "app/projects/page.tsx", "app/dashboard/page.tsx"]) {
    const count = silentReads(file).length;
    const allowed = LEGACY_SILENT_READS[file] ?? 0;
    assert.ok(count <= allowed, `${file}: ${count} lecturas tragan su error (se permiten ${allowed}). Anota el fallo como \`unread\`.`);
    assert.ok(count >= allowed, `${file}: ahora hay ${count}: baja LEGACY_SILENT_READS a ${count} para que el trinquete no retroceda`);
  }
});

test("5c · los ingresos del Panel y de Finanzas salen siempre de `settle`: un fallo se enseña como fallo", () => {
  const underSettle = /settle(<[^>]*>)?\(\s*\(\)\s*=>\s*$/;
  for (const file of ["app/dashboard/page.tsx", "app/cfo/page.tsx"]) {
    const code = stripComments(read(file));
    const reads = [...code.matchAll(/api\.revenue\w+/g)];
    assert.ok(reads.length > 0, `${file} no lee ingresos`);
    for (const match of reads) {
      const index = match.index ?? 0;
      if (underSettle.test(code.slice(Math.max(0, index - 60), index))) continue;
      // Si no está directamente bajo `settle`, tiene que estar dentro de un ayudante cuyas llamadas lo están.
      const helper = [...code.slice(0, index).matchAll(/(?:async\s+)?function\s+(\w+)/g)].at(-1)?.[1];
      assert.ok(helper !== undefined, `${file}: ${match[0]} no pasa por settle`);
      const calls = [...code.matchAll(new RegExp(String.raw`(?<!function\s)\b${helper}\(`, "g"))];
      assert.ok(calls.length > 0, `${file}: el ayudante ${helper} no se llama`);
      for (const call of calls) {
        assert.ok(underSettle.test(code.slice(Math.max(0, (call.index ?? 0) - 60), call.index)), `${file}: ${helper}() se llama fuera de settle`);
      }
    }
  }
});

test("5d · `settle` convierte un fallo en un fallo con su motivo, nunca en datos, y no tumba las demás lecturas", async () => {
  const boom = Object.assign(new Error("boom"), { status: 500, detail: "db down" });
  const [ok, failed, other] = await Promise.all([
    settle(async () => ({ entries: 3 })),
    settle(async () => {
      throw boom;
    }),
    settle(async () => ({ entries: 5 })),
  ]);
  assert.deepEqual(ok, { ok: true, data: { entries: 3 } }, "la lectura sana conserva su dato");
  assert.deepEqual(other, { ok: true, data: { entries: 5 } }, "otra lectura sana, también");
  assert.equal(failed.ok, false);
  if (!failed.ok) {
    assert.match(failed.message, /500/);
    assert.ok(!("data" in failed), "un fallo no lleva datos, ni vacíos ni cero");
  }
});

test("5e · un proyecto con una lectura fallida lo dice y conserva lo que ya estaba cargado", () => {
  const project: Project = { id: "p-1", objective_id: "o-1", name: "Proyecto", status: "VALIDATING" };
  const tasks: Task[] = [
    { id: "t1", project_id: "p-1", name: "product_validation", capability: "x", status: "COMPLETED", input: null, output: null, error: null },
  ];
  const decision: Decision = {
    id: "d1",
    project_id: "p-1",
    status: "GO",
    opportunity_score: 70,
    confidence: 0.8,
    rationale: "ok",
    correlation_id: "c1",
    evidence: [],
  };
  const audit: AuditEntry[] = [];

  const healthy = projectCard({ project, tasks, decision, audit });
  assert.deepEqual(healthy.unread, []);
  assert.equal(healthy.decisionLabel, "Aprobada");

  // La auditoría falla mientras tareas y decisión ya estaban cargadas: se conservan, y la fecha dice que no se pudo leer.
  const partial = projectCard({ project, tasks, decision, audit, unread: ["audit"] });
  assert.deepEqual(partial.unread, ["audit"]);
  assert.equal(partial.decisionLabel, "Aprobada", "lo ya cargado se conserva");
  assert.deepEqual(partial.progress, { done: 1, total: 1, ratio: 1 });
  assert.equal(partial.startedAt, null);
  assert.notEqual(UNREAD, NO_DATA);
});

test("5f · las pantallas pintan «No se pudo leer» donde una lectura falló, y no «Sin datos»", () => {
  const workspace = read("app/projects/projects-workspace.tsx");
  for (const [file, code] of [
    ["projects-workspace", workspace],
    ["projects-panels", read("app/projects/projects-panels.tsx")],
    ["cfo-panels", read("app/cfo/cfo-panels.tsx")],
  ]) {
    assert.ok(/\bUNREAD\b|UNREAD_VERDICT_TEXT/.test(code), `${file} no distingue una lectura fallida`);
  }
  assert.ok(/unread=\{agentsUnread\}/.test(workspace), "la tarjeta de agentes no sabe que su lectura puede fallar");
});
