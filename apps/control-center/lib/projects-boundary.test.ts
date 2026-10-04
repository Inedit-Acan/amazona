import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { AuditEntry, Decision, Project, Task } from "./api.ts";
import { portfolioCounts, projectCard, projectCodeFor, type ProjectSource } from "./projects-view.ts";

// Las fronteras de Proyectos (M45, Commit 11), al estilo de las del Panel y de Finanzas.
//
// Hasta el Commit 10 esta pantalla presentaba como actividad empresarial cosas que nadie había registrado: un
// «Beneficio real» calculado con pedidos generados, once proyectos de `lib/demo/projects.ts`, un capital expuesto que
// salía de una constante, una fecha de inicio a treinta días y una columna «Real» con ruido determinista.
//
// Igual que en Finanzas, unas invariantes se comprueban EJECUTANDO la lógica y otras LEYENDO el código: que una regla
// se cumpla hoy por casualidad no sirve si mañana alguien puede saltársela sin que nada se queje.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

/** Todo lo que construye o enseña la pantalla de Proyectos. */
const PROJECT_MODULES = ["lib/projects-view.ts", "lib/projects.ts", "app/projects/page.tsx", "app/projects/copy.ts", "app/projects/projects-workspace.tsx", "app/projects/projects-panels.tsx"];

const projectFiles = () =>
  readdirSync(join(ROOT, "app", "projects"), { withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .map((entry) => `app/projects/${entry.name}`);

/** El cuerpo de una función exportada, hasta la siguiente. Para mirar una tarjeta concreta. */
function bodyOf(file: string, name: string): string {
  const source = read(file);
  const start = source.indexOf(`export function ${name}`);
  assert.notEqual(start, -1, `${file} ya no exporta ${name}`);
  const rest = source.slice(start + 1);
  const end = rest.indexOf("\nexport function ");
  return end === -1 ? rest : rest.slice(0, end);
}

// --- Material de prueba ---------------------------------------------------------------------------------------------

const task = (name: string, status: Task["status"]): Task => ({
  id: `t-${name}`,
  project_id: "p-1",
  name,
  capability: name,
  status,
  input: null,
  output: null,
  error: null,
});

const PROJECT: Project = { id: "p-1", objective_id: "o-1", name: "Proyecto del Director ejecutivo", status: "VALIDATING" };

const DECISION: Decision = {
  id: "d-1",
  project_id: "p-1",
  status: "REVIEW",
  opportunity_score: 61,
  confidence: 0.55,
  rationale: "Falta cerrar el Legal Gate.",
  correlation_id: "c-1",
  evidence: [
    { source: "product_validation", summary: "ok", data: { recommendation: "GO" } },
    { source: "legal_validation", summary: "revisar", data: { recommendation: "REVIEW", risks: ["certificación pendiente"] } },
    { source: "finance_validation", summary: "proyección", data: { monthly_profit: 820.25, margin: 0.31 } },
  ],
};

const AUDIT: AuditEntry[] = [
  {
    id: "a-1",
    actor: "ceo",
    action: "project.created",
    resource: "project:p-1",
    before: null,
    after: null,
    correlation_id: "c-1",
    created_at: "2026-09-20T08:00:00Z",
  },
];

const SOURCE: ProjectSource = {
  project: PROJECT,
  tasks: [task("product_validation", "COMPLETED"), task("supplier_sourcing", "RUNNING"), task("finance_validation", "PENDING"), task("legal_validation", "PENDING")],
  decision: DECISION,
  audit: AUDIT,
};

// --- 1 · Ningún pedido generado -------------------------------------------------------------------------------------

test("1 · Proyectos no usa pedidos generados: ni `buildOrders` ni `operations-view`", () => {
  for (const file of PROJECT_MODULES) {
    const code = stripComments(read(file));
    assert.ok(!code.includes("buildOrders"), `${file} usa buildOrders: son pedidos generados, no ventas`);
    assert.ok(!code.includes("operations-view"), `${file} importa operations-view, de donde salían los pedidos generados`);
    assert.ok(!code.includes("economics-baseline"), `${file} usa buildBaseline, que rellena los huecos con supuestos de demostración`);
    assert.ok(!code.includes("economics-model"), `${file} evalúa el modelo económico del frontend: la proyección la da el backend`);
  }
});

// --- 2 · Ningún generador de demostración ---------------------------------------------------------------------------

test("2 · ningún módulo de Proyectos importa `lib/demo`, ni nombra un generador de demostración", () => {
  const importsDemo = /from\s+"(@\/lib\/demo\/[^"]+|\.{1,2}\/(?:\.{2}\/)*demo\/[^"]+)"/;
  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const code = stripComments(read(file));
    assert.ok(!importsDemo.test(code), `${file} importa lib/demo`);
    assert.ok(!/\bdemoRandom\b/.test(code), `${file} usa demoRandom: el ruido determinista no es un dato`);
    assert.ok(!/\bdemoProjects\b/.test(code), `${file} sigue fabricando proyectos`);
    assert.ok(!/\bDEMO_[A-Z_]+/.test(code), `${file} usa una constante DEMO_*`);
    assert.ok(!/status="demo"/.test(code), `${file} pinta una etiqueta de demostración: no debería haber nada que etiquetar`);
  }
});

test("2b · `lib/demo/projects.ts` ya no existe y nadie lo importa", () => {
  assert.ok(!existsSync(join(ROOT, "lib", "demo", "projects.ts")), "el generador de proyectos de demostración sigue en el árbol");
  for (const directory of ["app", "components", "lib"]) {
    const pending = [directory];
    while (pending.length > 0) {
      const current = pending.pop()!;
      for (const entry of readdirSync(join(ROOT, current), { withFileTypes: true })) {
        const relative = `${current}/${entry.name}`;
        if (entry.isDirectory()) {
          if (entry.name !== "node_modules") pending.push(relative);
        } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
          assert.ok(!stripComments(read(relative)).includes("demo/projects"), `${relative} importa el generador borrado`);
        }
      }
    }
  }
});

// --- 3 · Ningún proyecto inventado ----------------------------------------------------------------------------------

test("3 · los proyectos que enseña la pantalla son los que da el backend, uno por uno", () => {
  const card = projectCard(SOURCE);
  assert.equal(card.id, PROJECT.id);
  assert.equal(card.name, PROJECT.name);
  assert.equal(card.status, PROJECT.status);
  assert.equal(portfolioCounts([card]).total, 1, "un proyecto del backend es un proyecto en la cartera, ni uno más");

  // Los nombres que la demostración inventaba no pueden volver a aparecer en ningún sitio.
  const invented = ["AirPure X2", "EcoBottle", "SolarCharge", "SmartFeeder", "HomeCam", "AirDesk", "PetTracker", "TravelKit", "DeskLamp Pro", "GlowBand", "AquaFilter"];
  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const source = read(file);
    for (const name of invented) assert.ok(!source.includes(name), `${file} nombra el proyecto inventado ${name}`);
  }
});

test("3b · sin proyectos, el estado vacío no inventa contenido", () => {
  assert.equal(portfolioCounts([]).total, 0);
  assert.deepEqual(portfolioCounts([]), { total: 0, validation: 0, execution: 0, paused: 0, closed: 0, withPlan: 0 });

  const workspace = read("app/projects/projects-workspace.tsx");
  assert.ok(workspace.includes("projects.length === 0"), "la pantalla no distingue el caso sin proyectos");
  assert.ok(workspace.includes("EmptyState"), "el caso sin proyectos no usa el estado vacío compartido");
  const empty = workspace.slice(workspace.indexOf("projects.length === 0"), workspace.indexOf("const counts ="));
  assert.ok(!/\d+[.,]\d/.test(stripComments(empty)), "el estado vacío pinta una cifra");
  assert.ok(/un producto del catálogo no es un proyecto/i.test(empty), "el estado vacío no explica por qué está vacío");
});

// --- 4 · Ninguna cifra llamada «Beneficio real» ---------------------------------------------------------------------

test("4 · la expresión «Beneficio real» no aparece en el código de Proyectos, ni ninguna cifra se llama «real»", () => {
  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const code = stripComments(read(file));
    assert.ok(!/Beneficio\s+real/i.test(code), `${file} sigue nombrando un «Beneficio real»`);
    assert.ok(!/realProfit|capitalExposed/.test(code), `${file} conserva un campo de beneficio o capital inventado`);
    assert.ok(!/["'>]\s*Real\s*[<"']/.test(code), `${file} usa «Real» como etiqueta de una columna o de una cifra`);
  }
});

// --- 5 · «Sin datos» nunca es cero ----------------------------------------------------------------------------------

test("5 · un proyecto sin dato financiero dice «Sin datos», no cero", () => {
  const card = projectCard({ ...SOURCE, decision: null });
  assert.equal(card.plannedMonthlyProfit, null);
  assert.equal(card.plannedMargin, null);
  assert.equal(card.confidence, null);
  assert.equal(card.opportunityScore, null);
  assert.notEqual(card.plannedMonthlyProfit as unknown, 0);
  assert.notEqual(card.confidence as unknown, 0);

  // Y la pantalla no lo convierte en cero al pintarlo.
  const code = stripComments(read("app/projects/projects-panels.tsx")) + stripComments(read("app/projects/projects-workspace.tsx"));
  assert.ok(!/\?\?\s*0\b/.test(code), "algún valor ausente se pinta como cero con `?? 0`");
  assert.ok(!/\|\|\s*0\b/.test(code), "algún valor ausente se pinta como cero con `|| 0`");
});

// --- 6 · PLAN explícito, y PLAN que no se vuelve verificado ---------------------------------------------------------

test("6 · la proyección se identifica como PLAN, y su etiqueta no depende de que haya dato", () => {
  const card = projectCard(SOURCE);
  assert.equal(card.plannedMonthlyProfit?.provenance, "planned");

  const plan = bodyOf("app/projects/projects-panels.tsx", "PlanCard");
  const badge = plan.split("\n").find((line) => line.includes("DataProvenanceBadge"));
  assert.ok(badge !== undefined, "la tarjeta de proyección no lleva etiqueta de procedencia");
  assert.ok(badge.includes('status="planned"'), "la etiqueta de la proyección no dice PLAN");
  assert.ok(!/[?:]|&&/.test(badge), "la etiqueta de la proyección es condicional: desaparecería cuando no hay dato");
});

test("7 · una cifra PLAN no se presenta como registro, hecho, real ni verificado", () => {
  const plan = stripComments(bodyOf("app/projects/projects-panels.tsx", "PlanCard"));
  for (const forbidden of ['status="verified"', 'status="ledger"', "Registro verificado", "Declarado"]) {
    assert.ok(!plan.includes(forbidden), `la tarjeta de proyección usa «${forbidden}»`);
  }
  assert.ok(plan.includes("No ha ocurrido"), "la tarjeta de proyección no advierte de que la proyección no ha ocurrido");

  // Y al revés: ninguna tarjeta mezcla las dos procedencias en la misma etiqueta.
  for (const file of projectFiles()) {
    for (const line of stripComments(read(file)).split("\n")) {
      if (!line.includes("DataProvenanceBadge")) continue;
      const labels = ["planned", "verified", "ledger", "declared", "demo"].filter((label) => line.includes(`"${label}"`));
      assert.ok(labels.length <= 1, `${file} pinta una etiqueta con dos procedencias: ${labels.join(" + ")}`);
    }
  }
});

test("8 · la proyección no lleva moneda, porque la evidencia financiera no declara ninguna", () => {
  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const code = stripComments(read(file));
    assert.ok(!/\bformatEuro\b/.test(code), `${file} formatea un importe en euros sin que nadie haya declarado la moneda`);
    assert.ok(!code.includes("€"), `${file} escribe el símbolo del euro`);
  }
});

// --- 9 · Ninguna fecha calculada ------------------------------------------------------------------------------------

test("9 · una fecha que no está registrada no se sustituye por una calculada", () => {
  const card = projectCard({ ...SOURCE, audit: [] });
  assert.equal(card.startedAt, null);
  assert.ok(card.milestones.every((milestone) => milestone.at === null));

  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const code = stripComments(read(file));
    assert.ok(!/Date\.now\(\)/.test(code), `${file} calcula una fecha con Date.now()`);
    assert.ok(!/86_?400_?000|DAY_MS|daysAgo/.test(code), `${file} desplaza una fecha un número de días`);
    assert.ok(!/startOfDay/.test(code), `${file} sigue dependiendo del día del servidor para fabricar fechas`);
  }
});

// --- 10 · Los proyectos del Director ejecutivo conservan lo suyo ---------------------------------------------------

test("10 · tareas, decisión, riesgos y recomendaciones del proyecto del Director ejecutivo se conservan", () => {
  const card = projectCard(SOURCE);
  assert.deepEqual(card.progress, { done: 1, total: 4, ratio: 0.25 });
  assert.deepEqual(
    card.stages.map((stage) => [stage.task, stage.state]),
    [
      ["product_validation", "done"],
      ["supplier_sourcing", "current"],
      ["finance_validation", "todo"],
      ["legal_validation", "todo"],
    ],
  );
  assert.equal(card.stages[0].recommendation, "GO");
  assert.equal(card.stages[1].recommendation, null, "una etapa sin evidencia no recomienda nada");
  assert.equal(card.stages[3].recommendation, "REVIEW");
  assert.equal(card.decisionStatus, "REVIEW");
  assert.equal(card.decisionLabel, "Requiere revisión");
  assert.equal(card.confidence, 0.55);
  assert.equal(card.rationale, "Falta cerrar el Legal Gate.");
  assert.deepEqual(card.risks, [{ stage: "Legal", risk: "certificación pendiente" }]);
  assert.equal(card.startedAt, Date.parse("2026-09-20T08:00:00Z"));
  assert.equal(card.plannedMonthlyProfit?.value, 820.25);
});

// --- 11 · `projectCodeFor` intacto --------------------------------------------------------------------------------

test("11 · `projectCodeFor` no cambia: Aprobaciones, el Panel y Auditoría lo usan", () => {
  assert.equal(projectCodeFor(0), "AMZ-0024");
  assert.equal(projectCodeFor(23), "AMZ-0001");
  for (const file of ["app/approvals/page.tsx", "app/dashboard/page.tsx", "lib/audit-view.ts"]) {
    assert.ok(read(file).includes("projectCodeFor"), `${file} ya no usa projectCodeFor: revisa si el cambio le afecta`);
  }
});

// --- 12 · Proyectos sólo lee ---------------------------------------------------------------------------------------

test("12 · ninguna llamada de Proyectos escribe en el backend", () => {
  for (const file of [...PROJECT_MODULES, ...projectFiles()]) {
    const code = stripComments(read(file));
    assert.ok(!/method:\s*"(POST|PUT|PATCH|DELETE)"/.test(code), `${file} escribe en el backend`);
    for (const writer of ["approveApproval", "rejectApproval", "createObjective", "runPipeline"]) {
      assert.ok(!code.includes(writer), `${file} llama a ${writer}`);
    }
  }
});

// --- 13 · Un solo vocabulario ------------------------------------------------------------------------------------

test("13 · «Sin datos» es el mismo de Finanzas y del Panel, no una copia local", () => {
  const view = read("lib/projects-view.ts");
  assert.ok(/import\s*\{\s*NO_DATA\s*\}\s*from\s*"\.\/revenue-view\.ts"/.test(view), "projects-view define su propio «Sin datos» en vez de compartirlo");
  for (const file of projectFiles()) {
    const code = stripComments(read(file));
    assert.ok(!/"Sin datos"/.test(code), `${file} escribe «Sin datos» a mano en vez de usar NO_DATA`);
  }
});
