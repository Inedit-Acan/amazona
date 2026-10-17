import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA de /approvals y /status (M47, Commit 6b). Pruebas de texto: lo real y la demostración no se mezclan, un error no es un vacío, y
// ninguna fecha se inventa. Los componentes no se renderizan en `node --test`; esto vigila lo que su código puede y no puede hacer.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) =>
  source.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " ")).replace(/(^|[^:])\/\/.*$/gm, (_m, lead: string) => lead);
const code = (file: string) => stripComments(read(file));

const BACKEND_SIDE = ["app/approvals/backend-inbox.tsx", "lib/approvals-inbox.ts", "lib/approvals-reads.ts", "app/approvals/page.tsx"];

test("1 · la bandeja del backend no importa ni nombra nada de demostración", () => {
  for (const file of BACKEND_SIDE) {
    const source = code(file);
    assert.doesNotMatch(source, /lib\/demo|\/demo\/|demo-inbox|demoRequests|isDemo|approvals-view/, `${file} toca la demostración`);
  }
});

test("2 · la bandeja del backend no inventa fechas: ni reloj, ni «caducidad − 24 h», ni un SLA", () => {
  for (const file of ["app/approvals/backend-inbox.tsx", "lib/approvals-inbox.ts"]) {
    const source = code(file);
    assert.doesNotMatch(source, /Date\.now\(\)|new Date\(\)/, `${file} lee el reloj`);
    assert.doesNotMatch(source, /24\s*\*\s*HOUR|24\s*\*\s*3_?600|HOUR_MS\s*\*\s*24|slaHours|SLA/, `${file} calcula una fecha de solicitud o un SLA`);
  }
  const inbox = code("lib/approvals-inbox.ts");
  assert.match(inbox, /requestedAt = instantOf\(approval\.requested_at\)/, "la fecha de solicitud sale de requested_at");
  assert.match(inbox, /correlationId: approval\.correlation_id \?\? null/, "la correlación sale de correlation_id");
  assert.match(code("app/approvals/backend-inbox.tsx"), /Sin fecha de solicitud/, "sin dato, lo dice");
});

test("3 · la bandeja del backend no tiene severidad, «Críticas», solicitante ni indicadores de demostración", () => {
  const source = code("app/approvals/backend-inbox.tsx");
  assert.doesNotMatch(source, /severity|Severity|Crític|Aprobadas hoy|Tiempo medio|requester|solicitante/i);
});

test("4 · /approvals lee por `readApprovalsPage(api)` y no traga ningún error", () => {
  const page = code("app/approvals/page.tsx");
  assert.match(page, /readApprovalsPage\(api\)/);
  assert.doesNotMatch(page, /\.catch\(/);
  assert.match(page, /realInbox\(/);
});

test("5 · la demostración lleva su cartel «Datos de demostración» y no puede aprobar ni rechazar", () => {
  const source = code("app/approvals/demo-inbox.tsx");
  assert.match(source, /data-section="demo-banner"/);
  assert.match(source, /Datos de demostración/);
  assert.doesNotMatch(source, /api\.(approve|reject)|router\.refresh|approveApproval|rejectApproval/, "la demostración no escribe");
  assert.match(source, /<p className="text-sm font-medium">Datos de demostración<\/p>/, "el cartel es visible, no solo un comentario");
  assert.equal((source.match(/disabled\s+title="Solicitud de demostración"/g) ?? []).length, 2, "Aprobar y Rechazar están deshabilitados y lo dicen");
  assert.match(source, /<DataProvenanceBadge status="demo" compact tooltip="Solicitud de demostración/, "cada fila lleva su insignia DEMO");
});

test("6 · el contenedor separa en dos paneles: el del backend por defecto, la demostración aparte, nunca una lista común", () => {
  const source = code("app/approvals/approvals-workspace.tsx");
  assert.match(source, /useState<Panel>\("backend"\)/);
  assert.match(source, /panel === "backend" \? <BackendInboxPanel/);
  assert.match(source, /<DemoInbox/);
  assert.match(source, /<BackendInboxPanel inbox=\{inbox\} \/> : <DemoInbox/, "o uno o el otro: nunca los dos a la vez");
  assert.doesNotMatch(source, /demoRequests|requestFromApproval|requestFromReview|\.\.\.inbox\.requests/);
});

test("7 · «sin datos» y «no se pudo leer» son cosas distintas en el panel del backend", () => {
  const source = code("app/approvals/backend-inbox.tsx");
  assert.match(source, /inbox\.state === "empty"/, "el vacío es un estado propio");
  assert.match(source, /No se pudo leer una fuente/, "el error se dice");
  assert.match(source, /NOT_AVAILABLE/, "las cifras sin fuente son «No disponible»");
  // El estado vacío solo se pinta bajo `empty`; ninguna rama de error cae en él.
  assert.equal((source.match(/No hay solicitudes/g) ?? []).length, 1);
  assert.match(source, /inbox\.state === "empty" \? \(/, "«No hay solicitudes» solo bajo `empty` (nunca bajo `error`)");
  assert.match(source, /\[inbox\.sources\.approvals, inbox\.sources\.reviews\]\.flatMap/, "los avisos salen de las DOS fuentes");
  assert.match(source, /\{notices\.map\(/, "y se pintan todos");
  assert.match(source, /inbox\.state === "partial"\s*\?\s*"Ninguna solicitud en la fuente que sí se pudo leer\. Falta la otra: no se sabe si hay más\."/, "con una fuente caída, una lista vacía no dice «no hay»");
  assert.match(source, /inbox\.state === "partial" \? "" : /, "con una fuente caída no hay recuentos por pestaña");
  assert.match(source, /value === null \? NOT_AVAILABLE : formatInteger\(value\)/, "una cifra sin fuente es «No disponible», no 0");
});

test("8 · /status lee por `readStatusPage(api)`, sin ninguna lectura que trague su error", () => {
  const page = code("app/status/page.tsx");
  assert.match(page, /readStatusPage\(api\)/);
  assert.doesNotMatch(page, /\.catch\(/);
  assert.match(page, /statusFailures\(reads\)/);
  assert.doesNotMatch(page, /listOf\([^)]*\)\s*\?\?/, "una lectura caída llega como null, no como []");
  for (const key of ["agents", "executions", "incidents", "jobs", "pipelineRuns", "apiUsage"]) {
    assert.ok(page.includes(`${key}={listOf(reads.${key})}`), `${key} llega como null si falló`);
  }
});

test("9 · /status: un log de ejecuciones ilegible NO se sustituye por ejecuciones de demostración", () => {
  const source = code("app/status/status-workspace.tsx");
  assert.match(source, /executions === null \? \[\]/, "sin lectura no hay ejecuciones, tampoco de demostración");
  assert.match(source, /executions === null \? UNREADABLE_WORKERS/);
  assert.match(source, /runtimeReadable \? <AgentRuntimeCard/);
  assert.match(source, /runtimeReadable \? <CostCard/);
  assert.match(source, /data-section="status-read-failures"/);
  assert.match(source, /\{failures\.length > 0 \? \(/, "el aviso se pinta cuando hay fallos");
});

test("10 · ni /approvals ni /status convierten un fallo en `[]`", () => {
  for (const file of ["app/approvals/page.tsx", "app/status/page.tsx", "lib/approvals-reads.ts", "lib/status-reads.ts"]) {
    assert.doesNotMatch(code(file), /\.catch\(\s*\(\s*\)?\s*(?::[^=]+)?=>\s*(?:\[\]|null|undefined|0|\{\}|"")/, file);
  }
});

test("11 · ningún fichero de 6b lleva caracteres de control (un backspace de una barra invertida mal escrita)", () => {
  const files = [
    ...BACKEND_SIDE,
    "app/approvals/approvals-workspace.tsx",
    "app/approvals/demo-inbox.tsx",
    "app/status/page.tsx",
    "app/status/status-workspace.tsx",
    "lib/approval-labels.ts",
    "lib/status-reads.ts",
    "lib/status.ts",
    "lib/approvals-inbox.test.ts",
    "lib/approvals-reads.test.ts",
    "lib/status-reads.test.ts",
    "lib/approvals-status-boundary.test.ts",
  ];
  for (const file of files) {
    assert.doesNotMatch(read(file), /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/, `${file} tiene un carácter de control`);
  }
});
