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
