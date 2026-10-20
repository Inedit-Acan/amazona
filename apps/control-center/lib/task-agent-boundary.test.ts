import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA de la relación TAREA ↔ AGENTE (M48, Commit 7). Pruebas de texto sobre el código: impiden una línea concreta. La relación la calcula
// el backend; la pantalla no la infiere (ni por capacidad, ni por nombre, ni por orden) y no convierte un fallo de lectura en «sin tareas».

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
const code = (file: string) => stripComments(read(file));

const VIEW = "lib/task-agent.ts";
const READS = "lib/task-agent-reads.ts";
const LIST = "components/task-agent-list.tsx";
const STATUS_PAGE = "app/status/page.tsx";
const STATUS_WORKSPACE = "app/status/status-workspace.tsx";
const DETAILS = "components/neural-nexus/nexus-details.tsx";

test("la vista nunca empareja una tarea con un agente por capacidad, nombre u orden", () => {
  for (const file of [VIEW, READS, LIST]) {
    const source = code(file);
    assert.doesNotMatch(source, /capabilities\.includes|\.capability ===|\.name ===|indexOf\(|relatedTasks/, `${file} infiere la relación`);
  }
});

test("la lectura de «Tareas y agentes» no traga errores ni los convierte en una lista vacía", () => {
  for (const file of [READS, LIST, STATUS_PAGE]) assert.doesNotMatch(code(file), /\.catch\s*\(/, `${file} traga un error`);
  assert.match(code(READS), /readList\(/);
  assert.match(code(READS), /projectsContract\(/);
  assert.match(code(READS), /tasksContract\(/);
});

test("/status lee la relación UNA vez y la pasa a su tarjeta; su fallo no se mezcla con «Sin asignar»", () => {
  const page = code(STATUS_PAGE);
  assert.equal((page.match(/readMissionTaskAgents\(/g) ?? []).length, 1);
  assert.match(page, /taskAgentPanel\(/);
  assert.match(code(STATUS_WORKSPACE), /<TaskAgentCard panel=\{taskAgents\} \/>/);
});

test("la tarjeta distingue error, sin leer, vacío y cargado, y el error lleva su aviso (no una tabla)", () => {
  const list = code(LIST);
  assert.match(list, /panel\.kind === "error"[\s\S]*ReadErrorNotice/);
  assert.match(list, /panel\.kind === "unread"[\s\S]*No disponible/);
  assert.match(list, /panel\.kind === "empty"/);
  assert.match(list, /panel\.kind === "loaded"[\s\S]*TaskAgentTable/);
  for (const header of ["Tarea", "Agente asignado", "Ejecutado por", "Estado"]) assert.match(list, new RegExp(`>${header}<`));
});

test("el detalle de un agente enseña sus tareas desde `agentTasks`, y el del núcleo desde `missionTasks`", () => {
  const details = code(DETAILS);
  assert.match(details, /\{node\.agentTasks \? \(/);
  assert.match(details, /\{node\.missionTasks \? \(/);
  assert.doesNotMatch(details, /relatedTasks|por capacidad/);
});
