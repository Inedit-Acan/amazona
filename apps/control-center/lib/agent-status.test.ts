import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { AGENT_STATUSES, AGENT_STATUS_LABEL, agentStatusText, isOperational, readAgentStatus } from "./agent-status.ts";

// El vocabulario de estados de agente es del BACKEND (M47, Commit 1). La prueba central lee el `StrEnum` del backend y
// exige que el front conozca exactamente esos valores: si el backend añade o quita uno, el CI falla en vez de que el
// front lo pinte, en silencio, como «disponible».

const BACKEND_BASE = resolve(dirname(fileURLToPath(import.meta.url)), "../../../backend/app/agents/base.py");

/** Los miembros de `class AgentStatus(StrEnum)` del backend, tal como están escritos. */
function backendAgentStatuses(): string[] {
  const source = readFileSync(BACKEND_BASE, "utf8").replace(/\r\n/g, "\n");
  const block = source.match(/class AgentStatus\(StrEnum\):\n((?:[ \t]+.*\n|\n)+)/);
  assert.ok(block, "no se encontró `class AgentStatus(StrEnum)` en backend/app/agents/base.py: ¿se movió?");
  const members = [...block[1].matchAll(/^[ \t]+([A-Z_]+)\s*=\s*"([A-Z_]+)"/gm)];
  assert.ok(members.length > 0, "el StrEnum del backend no tiene miembros legibles");
  for (const [, name, value] of members) assert.equal(name, value, "el nombre y el valor del estado deberían coincidir");
  return members.map((member) => member[2]);
}

test("el front conoce EXACTAMENTE los estados del backend (contrato leído del StrEnum)", () => {
  assert.deepEqual([...AGENT_STATUSES].sort(), backendAgentStatuses().sort());
});

test("todos los estados del backend se leen como conocidos y tienen etiqueta", () => {
  for (const raw of backendAgentStatuses()) {
    const reading = readAgentStatus(raw);
    assert.equal(reading.kind, "known", raw);
    assert.ok(AGENT_STATUS_LABEL[raw as keyof typeof AGENT_STATUS_LABEL], `${raw} sin etiqueta`);
  }
});

test("lo que el backend NO envía es desconocido, jamás un estado conocido por defecto", () => {
  // OFFLINE y ERROR eran claves del mapa anterior y no existen en el backend.
  for (const raw of ["OFFLINE", "ERROR", "ONLINE", "ACTIVE", "IDLE", "available", "Available", " AVAILABLE", "", "x"]) {
    const reading = readAgentStatus(raw);
    assert.equal(reading.kind, "unknown", raw);
    assert.equal(isOperational(reading), false, `«${raw}» no puede contar como operativo`);
    assert.match(agentStatusText(reading), /^Desconocido/);
  }
});

test("solo AVAILABLE, BUSY y WAITING son operativos; BLOCKED, DEGRADED, DISABLED y FAILED no", () => {
  const operational = AGENT_STATUSES.filter((raw) => isOperational(readAgentStatus(raw)));
  assert.deepEqual(operational, ["AVAILABLE", "BUSY", "WAITING"]);
});

test("DEGRADED y WAITING tienen etiquetas distintas: no son el mismo estado", () => {
  assert.notEqual(AGENT_STATUS_LABEL.DEGRADED, AGENT_STATUS_LABEL.WAITING);
  assert.equal(AGENT_STATUS_LABEL.FAILED, "Fallido");
  assert.equal(AGENT_STATUS_LABEL.DISABLED, "Deshabilitado");
});

// --- M47 · Commit 1b: la única tabla de presentación ---------------------------------------------------------------------

import {
  AGENT_PRESENTATION,
  UNKNOWN_PRESENTATION,
  activityOfStatus,
  presentActivity,
  presentAgentStatus,
  summarizeAgentStatuses,
} from "./agent-status.ts";

test("la tabla de presentación cubre exactamente los estados del backend (leídos del StrEnum)", () => {
  assert.deepEqual(Object.keys(AGENT_PRESENTATION).sort(), backendAgentStatuses().sort());
});

test("etiquetas: AVAILABLE «Disponible», BLOCKED «Bloqueado», DEGRADED «Degradado», DISABLED «Deshabilitado», FAILED «Fallido»", () => {
  const label = (raw: string) => presentAgentStatus(readAgentStatus(raw)).label;
  assert.equal(label("AVAILABLE"), "Disponible");
  assert.equal(label("BLOCKED"), "Bloqueado");
  assert.equal(label("DEGRADED"), "Degradado");
  assert.equal(label("DISABLED"), "Deshabilitado");
  assert.equal(label("FAILED"), "Fallido");
  assert.equal(label("OFFLINE"), "Desconocido");
  // Ninguna etiqueta se repite: dos estados distintos nunca se ven igual.
  const labels = [...AGENT_STATUSES.map(label), UNKNOWN_PRESENTATION.label];
  assert.equal(new Set(labels).size, labels.length);
});

test("BUSY no es AVAILABLE; WAITING no es AVAILABLE ni DEGRADED", () => {
  const act = (raw: string) => activityOfStatus(raw);
  assert.notEqual(act("BUSY"), act("AVAILABLE"));
  assert.notEqual(act("WAITING"), act("AVAILABLE"));
  assert.notEqual(act("WAITING"), act("DEGRADED"));
  assert.notEqual(AGENT_PRESENTATION.BUSY.label, AGENT_PRESENTATION.AVAILABLE.label);
  assert.notEqual(AGENT_PRESENTATION.WAITING.label, AGENT_PRESENTATION.DEGRADED.label);
  // Y solo AVAILABLE produce «available».
  assert.deepEqual(AGENT_STATUSES.filter((raw) => act(raw) === "available"), ["AVAILABLE"]);
});

test("tonos: AVAILABLE y BUSY verdes, WAITING y DEGRADED ámbar, BLOCKED y FAILED rojos, DISABLED y desconocido neutros", () => {
  const tone = (raw: string) => presentAgentStatus(readAgentStatus(raw)).tone;
  assert.deepEqual(
    Object.fromEntries(AGENT_STATUSES.map((raw) => [raw, tone(raw)])),
    { AVAILABLE: "ok", BUSY: "ok", WAITING: "warn", BLOCKED: "bad", DEGRADED: "warn", DISABLED: "neutral", FAILED: "bad" },
  );
  assert.equal(UNKNOWN_PRESENTATION.tone, "neutral");
});

test("severidad de la alerta: FAILED y BLOCKED Alta, DEGRADED Media, el resto ninguna (DISABLED y desconocido incluidos)", () => {
  const alert = (raw: string) => presentAgentStatus(readAgentStatus(raw)).alert;
  assert.deepEqual(
    Object.fromEntries(AGENT_STATUSES.map((raw) => [raw, alert(raw)])),
    { AVAILABLE: null, BUSY: null, WAITING: null, BLOCKED: "Alta", DEGRADED: "Media", DISABLED: null, FAILED: "Alta" },
  );
  assert.equal(alert("OFFLINE"), null);
});

test("clasificación de la interfaz: operativos AVAILABLE, BUSY y WAITING; no operativos BLOCKED, DEGRADED, DISABLED y FAILED", () => {
  assert.deepEqual(AGENT_STATUSES.filter((raw) => AGENT_PRESENTATION[raw].operational), ["AVAILABLE", "BUSY", "WAITING"]);
  assert.deepEqual(AGENT_STATUSES.filter((raw) => !AGENT_PRESENTATION[raw].operational), ["BLOCKED", "DEGRADED", "DISABLED", "FAILED"]);
  assert.equal(UNKNOWN_PRESENTATION.operational, false);
});

test("presentActivity devuelve la misma fila que la tabla, para las ocho categorías", () => {
  for (const raw of AGENT_STATUSES) assert.equal(presentActivity(AGENT_PRESENTATION[raw].activity), AGENT_PRESENTATION[raw]);
  assert.equal(presentActivity("unknown"), UNKNOWN_PRESENTATION);
});

test("summarizeAgentStatuses: ocho estados mezclados dan 3 operativos, 4 no operativos y 1 desconocido (suman el total)", () => {
  const summary = summarizeAgentStatuses(["AVAILABLE", "BUSY", "WAITING", "BLOCKED", "DEGRADED", "DISABLED", "FAILED", "OFFLINE"]);
  assert.equal(summary.total, 8);
  assert.equal(summary.operational, 3);
  assert.equal(summary.notOperational, 4);
  assert.equal(summary.unknown, 1);
  assert.equal(summary.operational + summary.notOperational + summary.unknown, summary.total);
  assert.deepEqual(summary.byStatus, { AVAILABLE: 1, BUSY: 1, WAITING: 1, BLOCKED: 1, DEGRADED: 1, DISABLED: 1, FAILED: 1 });
  assert.deepEqual(summarizeAgentStatuses([]), {
    total: 0, operational: 0, notOperational: 0, unknown: 0,
    byStatus: { AVAILABLE: 0, BUSY: 0, WAITING: 0, BLOCKED: 0, DEGRADED: 0, DISABLED: 0, FAILED: 0 },
  });
});
