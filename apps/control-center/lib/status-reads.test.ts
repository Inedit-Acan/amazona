import assert from "node:assert/strict";
import { test } from "node:test";
import { readStatusPage, statusFailures, type StatusSource } from "./status-reads.ts";
import { FAILURES, INVALID_PAYLOADS, LOOKS_LIKE_ABSENCE, TECHNICAL, agent, execution } from "./read-test-support.ts";

// Las lecturas de /status (M47, Commit 6b). Antes había SEIS `.catch(...)`: la lista de agentes caída era `[]` («0 agentes») y un log de
// ejecuciones caído acababa cayendo a ejecuciones de DEMOSTRACIÓN. Ahora cada lectura es un `ReadState` y un fallo se dice.

const reject = (make: () => Error) => async (): Promise<never> => {
  throw make();
};

function fakeSource(over: Partial<StatusSource> = {}): StatusSource {
  return {
    listAgentExecutions: over.listAgentExecutions ?? (async () => []),
    listIncidents: over.listIncidents ?? (async () => []),
    listAgents: over.listAgents ?? (async () => []),
    listJobs: over.listJobs ?? (async () => []),
    listPipelineRuns: over.listPipelineRuns ?? (async () => []),
    listApiUsage: over.listApiUsage ?? (async () => []),
  };
}

const KEYS = ["executions", "incidents", "agents", "jobs", "pipelineRuns", "apiUsage"] as const;
const SOURCE_FOR: Record<(typeof KEYS)[number], keyof StatusSource> = {
  executions: "listAgentExecutions",
  incidents: "listIncidents",
  agents: "listAgents",
  jobs: "listJobs",
  pipelineRuns: "listPipelineRuns",
  apiUsage: "listApiUsage",
};

test("vacío válido ⇒ `empty` en las seis fuentes (un hecho, no un error)", async () => {
  const reads = await readStatusPage(fakeSource());
  assert.deepEqual(KEYS.map((key) => reads[key].kind), ["empty", "empty", "empty", "empty", "empty", "empty"]);
  assert.deepEqual(statusFailures(reads), []);
});

test("con datos ⇒ `loaded`", async () => {
  const reads = await readStatusPage(fakeSource({ listAgents: async () => [agent("a1")], listAgentExecutions: async () => [execution("e1", "a1")] }));
  assert.equal(reads.agents.kind, "loaded");
  assert.equal(reads.executions.kind, "loaded");
});

test("cada fuente que falla es `error` SOLO ella, con mensaje nuestro que ni es técnico ni parece una ausencia, y las demás siguen leyéndose", async () => {
  for (const key of KEYS) {
    for (const [name, make] of Object.entries(FAILURES)) {
      const reads = await readStatusPage(fakeSource({ [SOURCE_FOR[key]]: reject(make) }));
      for (const other of KEYS) {
        if (other === key) continue;
        assert.equal(reads[other].kind, "empty", `${key}/${name}: ${other}`);
      }
      const state = reads[key];
      assert.equal(state.kind, "error", `${key}/${name}`);
      if (state.kind !== "error") continue;
      assert.doesNotMatch(state.message, TECHNICAL, `${key}/${name}: ${state.message}`);
      assert.doesNotMatch(state.message, LOOKS_LIKE_ABSENCE, `${key}/${name}`);
    }
  }
});

test("una respuesta con la forma equivocada es `error`, nunca `empty`", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const bad = async () => payload as never;
    const reads = await readStatusPage(
      fakeSource({ listAgentExecutions: bad, listIncidents: bad, listAgents: bad, listJobs: bad, listPipelineRuns: bad, listApiUsage: bad }),
    );
    assert.deepEqual(KEYS.map((key) => reads[key].kind), Array(6).fill("error"), name);
  }
});

test("el backend caído: las seis son `error` y la lista de fallos tiene seis avisos distintos", async () => {
  const down = reject(FAILURES["conexión rechazada"]);
  const reads = await readStatusPage(
    fakeSource({ listAgentExecutions: down, listIncidents: down, listAgents: down, listJobs: down, listPipelineRuns: down, listApiUsage: down }),
  );
  const failures = statusFailures(reads);
  assert.equal(failures.length, 6);
  assert.equal(new Set(failures).size, 6);
});

test("`statusFailures` solo lista lo que falló, y nombra la fuente", async () => {
  const reads = await readStatusPage(fakeSource({ listAgents: reject(FAILURES["500"]) }));
  assert.deepEqual(statusFailures(reads), ["No se pudo cargar el registro de agentes."]);
});

test("una sola ronda: cada lectura se hace una vez", async () => {
  const calls: string[] = [];
  const counted = (name: string) => async () => {
    calls.push(name);
    return [];
  };
  await readStatusPage({
    listAgentExecutions: counted("e"),
    listIncidents: counted("i"),
    listAgents: counted("a"),
    listJobs: counted("j"),
    listPipelineRuns: counted("p"),
    listApiUsage: counted("u"),
  });
  assert.deepEqual(calls.sort(), ["a", "e", "i", "j", "p", "u"]);
});

test("`statusFailures` también avisa de una lectura que NO se hizo (`unread`)", async () => {
  const reads = await readStatusPage(fakeSource());
  const withUnread = { ...reads, jobs: { kind: "unread" as const, reason: "La cola no se leyó." } };
  assert.deepEqual(statusFailures(withUnread), ["La cola no se leyó."]);
});
