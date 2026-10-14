import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Frontera arquitectónica del estado de un agente (M47, Commit 1b). La interfaz tiene UNA tabla de estados de agente
// (lib/agent-status.ts) y ninguna copia: antes había una por pantalla —Agentes, Panel, Proyectos, el grafo— y dos
// comparaciones por literal, todas con el `OFFLINE` que el backend no envía y con `?? "available"` para el resto. Son
// pruebas de texto sobre el código fuente, deliberadamente: lo que impiden es una línea concreta.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
/** Quita los comentarios: se prohíbe CÓDIGO, no que un comentario explique por qué ya no existe. */
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relativePath = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "demo") continue;
      found.push(...sourceFiles(relativePath));
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.ts$/.test(entry.name) && entry.name !== "read-test-support.ts") {
      found.push(relativePath);
    }
  }
  return found;
}

const ALL = ["app", "components", "lib"].flatMap(sourceFiles);

/** Lo que habla de agentes (el resto de la aplicación tiene sus propios `FAILED`/`BLOCKED`: tareas, pagos, pedidos…). */
const AGENT_FILES = ALL.filter(
  (file) =>
    /^lib\/(agents|agents-view|agent-status|dashboard-view|status-view|neural-nexus|nexus-reads)\.ts$/.test(file) ||
    /^components\/(agent-card|agent-status-chip)\.tsx$/.test(file) ||
    /^components\/neural-nexus\//.test(file) ||
    /^app\/agents\//.test(file) ||
    file === "app/projects/projects-panels.tsx" ||
    /^app\/dashboard\/dashboard-(panels|workspace)\.tsx$/.test(file),
);

const STATUS_WORDS = "AVAILABLE|BUSY|WAITING|BLOCKED|DEGRADED|DISABLED|FAILED";

test("«OFFLINE» no existe como código en ninguna parte: el backend no lo envía", () => {
  const offenders = ALL.filter((file) => /["'`]OFFLINE["'`]|\bOFFLINE\s*:/.test(code(file)));
  assert.deepEqual(offenders, []);
});

test("ningún fichero que habla de agentes compara el estado contra un literal del backend", () => {
  const comparison = new RegExp(`\\.status\\s*[!=]==?\\s*["'](${STATUS_WORDS})["']|["'](${STATUS_WORDS})["']\\s*[!=]==?\\s*[\\w.?]*status\\b`);
  const offenders = AGENT_FILES.filter((file) => file !== "lib/agent-status.ts" && comparison.test(code(file)));
  assert.deepEqual(offenders, [], "usa readAgentStatus / presentAgentStatus / summarizeAgentStatuses");
});

test("ningún fichero afuera de lib/agent-status.ts declara una segunda tabla de estados de agente", () => {
  const table = new RegExp(`^\\s*["']?(${STATUS_WORDS})["']?\\s*:`, "m");
  for (const file of AGENT_FILES) {
    if (file === "lib/agent-status.ts") continue;
    const lines = code(file)
      .split("\n")
      .filter((line) => !/^\s*case\s/.test(line));
    assert.equal(table.test(lines.join("\n")), false, `${file} declara una tabla local de estados de agente`);
  }
  const named = /\b(?:const|let|var)\s+(ACTIVITY_TONE|ACTIVITY_LABEL|ACTIVITY_BY_STATUS|AGENT_STATUS|STATUS_FROM_REGISTRY)\b/;
  assert.deepEqual(ALL.filter((file) => named.test(code(file))), []);
});

test("ningún estado desconocido cae en «available» por defecto (`?? \"available\"`)", () => {
  for (const file of AGENT_FILES) {
    const offenders = code(file)
      .split("\n")
      .filter((line) => /\?\?\s*["']available["']/.test(line) && !line.includes("core?.status"));
    assert.deepEqual(offenders, [], file);
  }
});

test("las pantallas usan la fuente única: la misma tabla, el mismo chip, los mismos recuentos", () => {
  assert.match(code("lib/agents-view.ts"), /presentAgentStatus\(/);
  assert.match(code("lib/dashboard-view.ts"), /summarizeAgentStatuses\(/);
  assert.match(code("lib/status-view.ts"), /summarizeAgentStatuses\(/);
  assert.match(code("lib/agents.ts"), /summarizeAgentStatuses\(/);
  assert.match(code("lib/neural-nexus.ts"), /readAgentStatus\(/);
  for (const file of ["components/agent-card.tsx", "app/dashboard/dashboard-panels.tsx", "app/projects/projects-panels.tsx"]) {
    assert.match(code(file), /AgentStatusChip/, `${file} debe pintar el estado con AgentStatusChip`);
  }
});

test("el chip toma etiqueta y tono de la tabla única y lleva icono (el color nunca va solo)", () => {
  const chip = code("components/agent-status-chip.tsx");
  assert.match(chip, /presentActivity\(/);
  assert.match(chip, /Record<AgentActivity, LucideIcon>/, "un icono por cada categoría, exhaustivo");
  assert.doesNotMatch(chip, /["'](Disponible|Bloqueado|Degradado|Fallido|Deshabilitado|Ejecutando|En espera|Desconocido)["']/, "las etiquetas son de la tabla, no del chip");
});

test("el Panel no habla de «en línea» ni de porcentaje de agentes operativos", () => {
  const view = code("lib/dashboard-view.ts");
  const workspace = code("app/dashboard/dashboard-workspace.tsx");
  assert.doesNotMatch(view + workspace, /en línea|agentsOnline|agentsRatio/i);
  assert.doesNotMatch(workspace, /label="Agentes en línea"/);
});
