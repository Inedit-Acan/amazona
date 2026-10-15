import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA de honestidad del Decision Engine (M47, Commit 4). Pruebas de texto sobre el código, deliberadamente: lo que impiden es una
// línea concreta. Fijan que la capa de datos, estado y HUD del grafo solo dice lo que el backend sabe: nada de costes, tareas, progreso ni
// handoffs de demostración; ninguna tarea «asignada» a un agente que el backend no registra; ningún error convertido en vacío.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
const code = (file: string) => stripComments(read(file));

const MODEL = "lib/neural-nexus.ts";
const READS = "lib/nexus-reads.ts";
const MISSION = "lib/nexus-mission.ts";
const STATE = "lib/nexus-engine-state.ts";
const DOMAINS_FILE = "lib/nexus-domains.ts";
const GRAPH = "components/neural-nexus/neural-nexus-graph.tsx";
const HUD = "components/neural-nexus/nexus-hud.tsx";
const DETAILS = "components/neural-nexus/nexus-details.tsx";
const LEGEND = "components/neural-nexus/nexus-legend.tsx";
const TOOLBAR = "components/neural-nexus/nexus-toolbar.tsx";
const TWO_D = "components/neural-nexus/nexus-2d.tsx";
const CARD = "components/ceo/agent-network-card.tsx";
const CONTEXT = "components/ceo/ceo-context.tsx";

/** La capa PRODUCTIVA del Decision Engine: datos, estado y HUD. La escena 3D (`scene/**`) queda fuera: no se toca. */
const LAYER = [MODEL, READS, MISSION, STATE, DOMAINS_FILE, GRAPH, HUD, DETAILS, LEGEND, TOOLBAR, TWO_D, CARD, CONTEXT];

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of LAYER) assert.ok(read(file).length > 100, `${file} no existe o está vacío`);
});

test("lo de demostración del grafo desapareció: ni el módulo `lib/demo/neural-nexus.ts` ni sus exportaciones", () => {
  assert.equal(existsSync(join(ROOT, "lib/demo/neural-nexus.ts")), false, "el módulo de demostración del grafo vuelve a existir");
  for (const file of LAYER) {
    assert.doesNotMatch(read(file), /\/demo\/|lib\/demo/, `${file} importa lib/demo`);
    assert.doesNotMatch(
      code(file),
      /\b(DEMO_TASKS|DEMO_HANDOFFS|DEMO_PROJECT|DEMO_CORE_METRICS|CANONICAL_AGENTS|demoProgress|demoEvaluation|demoTaskIndex)\b/,
      `${file} usa una constante o función de demostración`,
    );
  }
});

test("el coste no existe en el Decision Engine: ni `COST_PER_RUN`, ni `costToday`, ni «Coste hoy», ni ninguna cifra en euros", () => {
  for (const file of LAYER) {
    const source = code(file);
    assert.doesNotMatch(source, /COST_PER_RUN|costToday|Coste hoy|\bformatEuro\b|\bevaluationScore\b/, `${file} vuelve a hablar de coste o de evaluación`);
  }
});

test("el estado del nodo NO se infiere de una decisión ni de una tarea: el modelo no conoce evidencias, vetos ni estados de tarea", () => {
  const model = code(MODEL);
  assert.doesNotMatch(model, /EVIDENCE_BY_CAPABILITY|REGISTRY_OVERRIDES_DECISION|finance_veto|legal_status|\bevidence\b|\bDecision\b(?!\s+Engine)/, "el modelo del grafo vuelve a derivar el estado de la decisión");
  assert.doesNotMatch(model, /coreStatus\(/, "el estado del núcleo no sale de una decisión");
  assert.doesNotMatch(model, /task\.status|\.status === "(FAILED|RUNNING|WAITING_APPROVAL|COMPLETED)"/, "el estado de un agente no sale del estado de una tarea");
  assert.match(model, /readAgentStatus\(/);
});

test("una tarea emparejada por capacidad NUNCA se rotula «asignada» ni «actual de <agente>»; se llama «relacionada» y dice por qué", () => {
  for (const file of LAYER) {
    const source = code(file);
    assert.doesNotMatch(source, /asignad[oa]s?|Tarea actual|tarea actual|assigned_agent/i, `${file} habla de asignación o de «tarea actual»`);
  }
  const details = code(DETAILS);
  assert.match(details, /Tarea[s]? relacionada[s]?/);
  assert.match(details, /capacidad/i);
  assert.match(details, /No registra qué agente|no registra qué agente/);
});

test("una tarea FAILED no marca a un agente: `relatedTasks`/`relatedBasis` informan, y ningún lugar traduce tareas a `status:` de nodo", () => {
  const model = code(MODEL);
  assert.match(model, /relatedBasis: "capability"/);
  assert.doesNotMatch(model, /\bstatus\b[^\n]*\brelated(Tasks)?\b/, "el estado de un nodo no se calcula con tareas relacionadas");
});

test("la confianza de la decisión NO alimenta el progreso: ni el núcleo de misión ni el estado ni el HUD la nombran", () => {
  for (const file of [MISSION, STATE, HUD]) assert.doesNotMatch(code(file), /\bconfidence\b|\bopportunity_score\b/, `${file} lee la confianza`);
  assert.doesNotMatch(code(MODEL), /\bprogress\b/);
  assert.match(code(MISSION), /COMPLETED/);
  assert.match(code(MISSION), /CANCELLED/);
});

test("«Evidencias de la decisión» (no «Eventos activos») y su valor es exactamente `evidence.length`", () => {
  const state = code(STATE);
  assert.match(state, /"Evidencias de la decisión"/);
  assert.match(state, /evidence\.length/);
  for (const file of LAYER) assert.doesNotMatch(code(file), /Eventos activos|activeEvents/, `${file} vuelve a decir «Eventos activos»`);
});

test("el proyecto se enseña con su NOMBRE: ningún `project_id` se pinta como nombre en el modelo, el estado, el HUD o el detalle", () => {
  for (const file of [MODEL, STATE, HUD, DETAILS, GRAPH]) assert.doesNotMatch(code(file), /project_id/, `${file} usa el id del proyecto`);
  assert.match(code(STATE), /project\.name/);
});

test("ninguna lectura traga un error: ni `.catch(` en la capa productiva", () => {
  for (const file of LAYER) assert.doesNotMatch(code(file), /\.catch\s*\(/, `${file} traga un error`);
  assert.match(code(READS), /readList\(/);
  assert.match(code(MISSION), /readList\(/);
});

test("`isDemo` no sustituye a la procedencia: no existe `isDemo` y cada campo del HUD se clasifica como recorded / derived / unavailable", () => {
  for (const file of LAYER) assert.doesNotMatch(code(file), /\bisDemo\b/, `${file} usa isDemo`);
  assert.match(code(STATE), /"recorded" \| "derived" \| "unavailable"/);
  const hud = code(HUD);
  assert.match(hud, /data-provenance/);
  assert.doesNotMatch(code(DETAILS), /status=\{node\.isDemo/);
});

test("el grafo y el panel rotulan sin mezcla real/demo: el pie ya no habla de datos de demostración", () => {
  assert.doesNotMatch(code(GRAPH), /demostración/i);
  assert.doesNotMatch(code(DETAILS), /demostración/i);
  assert.doesNotMatch(code(HUD), /demostración/i);
});

test("la sesión y lo persistido se concilian con la máquina de estados (y no con un `useState` suelto de la decisión)", () => {
  const graph = code(GRAPH);
  assert.match(graph, /reduceEngine/);
  assert.match(graph, /engineView\(/);
  assert.match(graph, /engineHud\(/);
  assert.match(graph, /read_requested/);
  assert.match(graph, /read_result/);
  assert.match(graph, /mission_created/);
  assert.doesNotMatch(graph, /decision: Decision \| null|decisionUnavailable/);
  const context = code(CONTEXT);
  assert.match(context, /notifyMission/);
  assert.doesNotMatch(context, /DecisionState|setDecision/);
});

test("tras «Crear misión» se relee: la tarjeta avisa a la misión y la misión avisa al contexto", () => {
  assert.match(code("components/ceo/mission-form.tsx"), /notifyMission\(/);
  assert.match(code(GRAPH), /missionEvent/);
  // El efecto de lectura depende de la misión: cada misión nueva dispara una lectura.
  assert.match(code(GRAPH), /\[attempt,\s*missionEvent/);
});

test("la escena 3D no depende de la capa de misión: `scene/**` no importa el estado de la misión ni las tareas", () => {
  for (const file of [
    "components/neural-nexus/scene/nexus-scene.tsx",
    "components/neural-nexus/scene/nexus-edge.tsx",
    "components/neural-nexus/scene/precision-node.tsx",
    "components/neural-nexus/scene/orbit-rings.tsx",
    "components/neural-nexus/scene/nexus-lighting.tsx",
  ]) {
    assert.doesNotMatch(read(file), /nexus-mission|nexus-engine-state|nexus-reads/, `${file} depende de la misión`);
  }
});

test("la capa de misión es pura y de solo lectura: ni escribe en el backend ni usa el reloj", () => {
  for (const file of [MISSION, STATE]) {
    const source = code(file);
    assert.doesNotMatch(source, /createObjective|runObjective|method:\s*"(POST|PUT|PATCH|DELETE)"|\bapi\.[a-z]+\(/, `${file} escribe o llama a la API directamente`);
    assert.doesNotMatch(source, /Date\.now\(|new Date\(\)/, `${file} usa el reloj`);
  }
});

test("el progreso sale solo de las tareas y solo existe en la capa de misión", () => {
  assert.match(code(MISSION), /export function taskProgress/);
  assert.doesNotMatch(code(GRAPH), /taskProgress|\.confidence/);
  assert.doesNotMatch(code(HUD), /taskProgress|\.confidence/);
});
