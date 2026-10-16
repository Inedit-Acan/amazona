import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5). Son pruebas de texto sobre el código, deliberadamente:
// lo que impiden es una línea concreta. Fijan que los dos bloques solo leen datos del backend, sin demostración ni azar, que no hay
// porcentajes ni «Ver todas», que el selector 7/14/30 no los gobierna, que «Próximos hitos» sigue sin fuente y que el Decision Engine
// del Commit 4 conserva su `domainOfRole`.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
const code = (file: string) => stripComments(read(file));

const ACTIVITY = "lib/ceo-activity.ts";
const AREAS = "lib/ceo-area-executions.ts";
const CONTRACTS = "lib/ceo-activity-contracts.ts";
const READS = "lib/ceo-activity-reads.ts";
const ACTIVITY_UI = "components/ceo/activity-block.tsx";
const AREAS_UI = "components/ceo/area-executions-block.tsx";
const BOTTOM = "components/ceo/bottom-row.tsx";

const LIB = [ACTIVITY, AREAS, CONTRACTS, READS];
const UI = [ACTIVITY_UI, AREAS_UI, BOTTOM];
const ALL = [...LIB, ...UI];

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of ALL) assert.ok(read(file).length > 100, `${file} no existe o está vacío`);
});

test("ningún fichero importa demostración, la vista antigua de auditoría ni el selector de periodo, ni usa azar", () => {
  for (const file of ALL) {
    const text = code(file);
    assert.doesNotMatch(text, /lib\/demo|\.\/demo\/|\.\.\/demo\//, `${file} importa lib/demo`);
    assert.doesNotMatch(text, /audit-view|demoRows|isDemo|demoRandom/, `${file} usa la vista antigua de auditoría`);
    assert.doesNotMatch(text, /Math\.random|crypto\.getRandomValues/, `${file} usa azar`);
    assert.doesNotMatch(text, /PeriodSelect|parseRevenueDays|revenueWindow/, `${file} toca el selector 7/14/30`);
    assert.doesNotMatch(text, /\.catch\s*\(/, `${file} traga un error`);
  }
});

test("el selector 7/14/30 gobierna solo Ingresos: estos bloques no reciben `window`, `days` ni `dias`", () => {
  for (const file of [...LIB, ACTIVITY_UI, AREAS_UI]) assert.doesNotMatch(code(file), /\b(window|days|dias)\b\s*[:=,)]/, file);
  assert.doesNotMatch(code(BOTTOM), /\b(days|dias)\b/);
});

test("rótulos aprobados: «Actividad registrada» y «Ejecuciones por área»; ni «Actividad reciente» ni «Rendimiento por área»", () => {
  assert.match(code(ACTIVITY), /title: "Actividad registrada"/);
  assert.match(code(AREAS), /title: "Ejecuciones por área"/);
  for (const file of ALL) {
    assert.doesNotMatch(code(file), /Actividad reciente|Rendimiento por [aá]rea|Rendimiento por agente/, `${file} usa un rótulo retirado`);
  }
  const bottom = code(BOTTOM);
  assert.match(bottom, /ActivityBlock|ActivityCard/);
  assert.match(bottom, /title="Próximos hitos"/);
});

test("sin porcentajes: ningún `%` en los módulos de ejecuciones por área ni en su tarjeta, ni cifras del mockup", () => {
  for (const file of [AREAS, AREAS_UI]) assert.doesNotMatch(code(file), /%/, `${file} escribe un porcentaje`);
  for (const file of ALL) {
    assert.doesNotMatch(code(file), /\b(92|78|65|88|90|76|81)\b/, `${file} lleva una cifra del mockup`);
  }
});

test("ninguna palabra de rendimiento: tasa de éxito, eficiencia, SLA, uptime, coste ni tendencia", () => {
  for (const file of [AREAS, AREAS_UI]) {
    assert.doesNotMatch(code(file), /tasa de [eé]xito|successRate|eficiencia|\bSLA\b|uptime|tendencia|coste|\bcost\b|trend/i, `${file} habla de un rendimiento que no se mide`);
  }
});

test("«Verificado» no existe en estos ficheros; la procedencia es registrado / derivado / no disponible", () => {
  for (const file of ALL) assert.doesNotMatch(code(file), /["'`]Verificad[oa]s?["'`]|status="(verified|ledger)"/, file);
  assert.match(code(ACTIVITY), /recorded/);
  assert.match(code(ACTIVITY), /derived/);
});

test("ni «Ver todas» ni enlace a /agents o /audit en estos bloques (D-5-5)", () => {
  for (const file of [ACTIVITY_UI, AREAS_UI, BOTTOM]) {
    const text = code(file);
    assert.doesNotMatch(text, /Ver todas|seeAll|href=["'{`]\/?(agents|audit)/, `${file} enlaza a una pantalla que no es su detalle`);
  }
});

test("la guarda de las 500 entradas está en el código: `>= AUDIT_API_LIMIT` ⇒ no disponible, nunca cargado", () => {
  assert.match(code(ACTIVITY), /AUDIT_API_LIMIT\s*=\s*500/);
  assert.match(code(ACTIVITY), /length\s*>=\s*AUDIT_API_LIMIT/);
  assert.match(code(AREAS), /EXECUTIONS_API_LIMIT\s*=\s*100/);
});

test("el orden sale del instante y del id, nunca del orden de la API ni del índice del array", () => {
  const text = code(ACTIVITY);
  assert.match(text, /parseUtc\(/);
  assert.doesNotMatch(text, /\.reverse\(\)/, "invertir el array de la API no es ordenar");
  assert.doesNotMatch(text, /\.slice\(\s*-\s*\d|\.slice\(\s*-VISIBLE/, "las últimas N por posición del array");
});

test("el área se deriva con `strictDomainOfRole`, no con `domainOfRole` (que cae en «Operaciones»)", () => {
  for (const file of [ACTIVITY, AREAS]) assert.doesNotMatch(code(file), /\bdomainOfRole\b/, `${file} usa el fallback de Operaciones`);
  assert.match(code(AREAS), /export function strictDomainOfRole/);
  assert.match(code(ACTIVITY), /strictDomainOfRole/);
  const domains = code("lib/nexus-domains.ts");
  assert.match(domains, /export function domainOfRole\(role: string\): DomainKey \{[\s\S]*?: "Operaciones";/);
  assert.doesNotMatch(domains, /strictDomainOfRole/, "el Decision Engine no se toca");
});

test("el actor con correo no se pinta: la regla de privacidad vive en el módulo de actividad", () => {
  assert.match(code(ACTIVITY), /includes\("@"\)/);
  assert.match(code(ACTIVITY), /"Persona"/);
  assert.match(code(ACTIVITY), /"Orquestador"/);
});

test("ni «OK», «Éxito» ni «Correcta» para una entrada de auditoría", () => {
  assert.doesNotMatch(code(ACTIVITY) + code(ACTIVITY_UI), /["'`](OK|Ok|Éxito|Exito|Correcta|Sin error registrado)["'`]/);
});

test("la categoría reutiliza `lib/audit.ts` (puro), no `audit-view.ts`", () => {
  assert.match(code(ACTIVITY), /from "\.\/audit\.ts"/);
  assert.match(code(ACTIVITY), /eventCategory|isErrorAction/);
});

test("la lectura sale de UN sitio: `readActivityNow(api)` con el cliente de servidor, y solo las tres fuentes aprobadas", () => {
  const bottom = code(BOTTOM);
  assert.match(bottom, /readActivityNow\(api\)/);
  assert.match(bottom, /from "@\/lib\/api-server"/);
  const reads = code(READS);
  for (const call of ["listAudit()", "listAgents()", "listAgentExecutions()"]) assert.ok(reads.includes(call), `falta ${call}`);
  assert.doesNotMatch(reads, /listApprovals|listIncidents|listProjects|listTasks|listJobs|listDecisions|listPipeline/);
});

test("Próximos hitos sigue «No disponible»: sin fuente, sin fechas literales ni lectura", () => {
  const bottom = code(BOTTOM);
  assert.match(bottom, /title="Próximos hitos" state=\{unavailableState\(/);
  assert.doesNotMatch(bottom, /\b20\d\d-\d\d-\d\d\b|\b\d{1,2} (ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\b|\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic) 20\d\d\b/i);
  assert.doesNotMatch(bottom, /expires_at|milestone|roadmap|\bhito\w*\s*[:=]\s*\[/i);
});

test("la rejilla inferior conserva sus columnas: 1 → 2 → 3", () => {
  assert.match(read(BOTTOM), /grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3/);
});

test("un fallo de un bloque no apaga al otro: cada tarjeta recibe SU vista, y la página no lee nada", () => {
  const bottom = code(BOTTOM);
  assert.match(bottom, /activity=\{|views\.activity/);
  assert.match(bottom, /areas=\{|views\.areas/);
  assert.doesNotMatch(read("app/ceo/page.tsx"), /listAudit|listAgentExecutions/);
});

test("ningún fichero de este commit contiene el byte 0x08 (un `\b` convertido por una herramienta de edición)", () => {
  const files = [...ALL, "lib/ceo-activity-test-support.ts", "lib/ceo-activity.test.ts", "lib/ceo-activity-contracts.test.ts", "lib/ceo-activity-reads.test.ts", "lib/ceo-area-executions.test.ts", "lib/ceo-activity-boundary.test.ts"];
  for (const file of files) assert.equal(readFileSync(join(ROOT, file)).includes(0x08), false, `${file} contiene 0x08`);
});
