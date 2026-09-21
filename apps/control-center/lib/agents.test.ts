import assert from "node:assert/strict";
import { test } from "node:test";
import { agentStats, executionsByAgent, fleetSummary, groupByTeam, runsByTeam, teamOf, withinWindow } from "./agents.ts";

const agent = (id: string, role: string, status = "AVAILABLE", name = id) => ({ id, role, status, name });
const run = (agent_id: string, success: boolean, duration_ms: number, created_at: string) => ({ agent_id, success, duration_ms, created_at });

test("teamOf y groupByTeam agrupan por equipo de la spec, ordenan y ocultan los vacíos", () => {
  assert.equal(teamOf("cfo"), "Finanzas");
  assert.equal(teamOf("legal_compliance"), "Legal");
  assert.equal(teamOf("inventado"), "Otros");
  const groups = groupByTeam([agent("a", "cfo", "AVAILABLE", "CFO"), agent("b", "research", "AVAILABLE", "Zeta"), agent("c", "product", "AVAILABLE", "Alfa"), agent("d", "x", "AVAILABLE", "Raro")]);
  assert.deepEqual(
    groups.map((g) => [g.team, g.agents.map((a) => a.name)]),
    [
      ["Investigación", ["Alfa", "Zeta"]],
      ["Finanzas", ["CFO"]],
      ["Otros", ["Raro"]],
    ],
  );
});

test("agentStats: ejecuciones, fallos, tasa de éxito, latencia media y última actividad", () => {
  const stats = agentStats([
    { success: true, duration_ms: 10, created_at: "2026-09-20T10:00:00" },
    { success: false, duration_ms: 30, created_at: "2026-09-21T10:00:00" },
  ]);
  assert.equal(stats.runs, 2);
  assert.equal(stats.failures, 1);
  assert.equal(stats.successRate, 0.5);
  assert.equal(stats.avgLatencyMs, 20);
  // las fechas sin zona del backend son UTC
  assert.equal(stats.lastActivity?.getTime(), new Date("2026-09-21T10:00:00Z").getTime());
  assert.deepEqual(agentStats([]), { runs: 0, failures: 0, successRate: null, avgLatencyMs: null, lastActivity: null });
});

test("fleetSummary cuenta estados, éxito global y agentes con errores", () => {
  const agents = [agent("a", "cfo"), agent("b", "legal", "BUSY"), agent("c", "product", "DISABLED")];
  const summary = fleetSummary(agents, [run("a", true, 4, "2026-09-21T10:00:00"), run("a", false, 6, "2026-09-21T11:00:00"), run("b", true, 5, "2026-09-21T12:00:00")]);
  assert.deepEqual(summary, {
    registered: 3,
    available: 1,
    busy: 1,
    other: 1,
    runs: 3,
    successRate: 2 / 3,
    avgLatencyMs: 5,
    agentsWithErrors: 1,
  });
  assert.equal(fleetSummary([], []).successRate, null);
});

test("executionsByAgent agrupa por agent_id", () => {
  const map = executionsByAgent([run("a", true, 1, "x"), run("b", true, 1, "x"), run("a", false, 1, "x")]);
  assert.equal(map.get("a")?.length, 2);
  assert.equal(map.get("b")?.length, 1);
});

test("withinWindow filtra por antigüedad interpretando las fechas sin zona como UTC", () => {
  const now = new Date("2026-09-21T12:00:00Z").getTime();
  const rows = [
    { created_at: "2026-09-21T10:00:00" }, // hace 2 h
    { created_at: "2026-09-19T12:00:00" }, // hace 2 días
    { created_at: "2026-08-01T12:00:00Z" }, // hace 51 días
  ];
  assert.equal(withinWindow(rows, "all", now).length, 3);
  assert.equal(withinWindow(rows, "24h", now).length, 1);
  assert.equal(withinWindow(rows, "7d", now).length, 2);
  assert.equal(withinWindow(rows, "30d", now).length, 2);
});

test("runsByTeam cuenta las ejecuciones por equipo del agente", () => {
  const agents = [agent("a", "cfo"), agent("b", "legal"), agent("c", "legal_compliance")];
  assert.deepEqual(runsByTeam(agents, [{ agent_id: "b" }, { agent_id: "c" }, { agent_id: "a" }, { agent_id: "zzz" }]), [
    { team: "Legal", runs: 2 },
    { team: "Finanzas", runs: 1 },
    { team: "Otros", runs: 1 },
  ]);
});
