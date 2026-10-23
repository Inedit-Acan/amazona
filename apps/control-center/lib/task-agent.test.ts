import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentRelation, AssignmentStatus, ExecutionTrace, RecoveryKind, Task, TaskRecovery } from "./api.ts";
import { agentTaskRows, recoveryOf, taskAgentRows, TASK_AGENT_UNAVAILABLE_LABEL, UNKNOWN_AGENT_LABEL } from "./task-agent.ts";

// La relación TAREA ↔ AGENTE en pantalla (M48, Commit 7). La relación la calcula el backend (`agent_relation`); aquí solo se escribe. Lo que
// estas pruebas fijan: asignación ≠ ejecución (nunca se funden), un agente que el registro no conoce se dice «Agente desconocido» (nunca
// un nombre ni «Disponible»), la desviación se ve, y NADA se infiere de la capacidad, del nombre de la tarea ni del orden.

const agent = (id: string, name: string, capabilities: string[] = []): Agent => ({
  id,
  name,
  role: "x",
  capabilities,
  status: "AVAILABLE",
  reliability_score: 1,
  version: "1",
  cost_profile: {},
});

const AGENTS = [
  agent("agent-product-1", "Product Validation Agent", ["market_validation"]),
  agent("agent-supplier-1", "Supplier Sourcing Agent", ["supplier_sourcing"]),
  agent("agent-legal-1", "Legal Validation Agent", ["legal_validation"]),
];

const trace = (agentId: string, over: Partial<ExecutionTrace> = {}): ExecutionTrace => ({
  source: "execution_log",
  execution_id: "e-1",
  agent_id: agentId,
  agent_known: AGENTS.some((item) => item.id === agentId),
  success: true,
  attempt: 1,
  assigned_agent_id: null,
  started_at: "2026-10-20T12:00:00Z",
  completed_at: "2026-10-20T12:00:01Z",
  created_at: "2026-10-20T12:00:01Z",
  ...over,
});

const relation = (status: AssignmentStatus, over: Partial<AgentRelation> = {}): AgentRelation => ({
  status,
  assigned_agent_id: null,
  assigned_agent_known: null,
  executed_by_agent_id: null,
  reassigned: false,
  executions: [],
  ...over,
});

const task = (id: string, over: Partial<Task> = {}): Task => ({
  id,
  project_id: "p-1",
  name: `tarea ${id}`,
  capability: "market_validation",
  status: "COMPLETED",
  input: null,
  output: null,
  error: null,
  depends_on: [],
  ...over,
});

const rowOf = (item: Task, agents: Agent[] | null = AGENTS) => taskAgentRows([item], agents)[0];

// --- A · B · C · sin asignar, asignada, desconocida ------------------------------------------------------------------------------------

test("A · una tarea sin asignar se dice «Sin asignar», aunque haya un agente con su capacidad en el registro", () => {
  const row = rowOf(task("t", { status: "PENDING", assigned_agent_id: null, agent_relation: relation("UNASSIGNED") }));
  assert.equal(row.assigned.label, "Sin asignar");
  assert.equal(row.state, "Sin asignar");
  assert.equal(row.executedBy, null);
  assert.equal(row.status, "UNASSIGNED");
});

test("B · una tarea asignada a un agente que existe enseña el NOMBRE de ese agente, y su estado es el de la tarea", () => {
  const row = rowOf(
    task("t", { status: "PENDING", assigned_agent_id: "agent-product-1", agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }) }),
  );
  assert.equal(row.assigned.label, "Product Validation Agent");
  assert.equal(row.assigned.id, "agent-product-1");
  assert.equal(row.state, "Pendiente");
});

test("C · un agente asignado que el registro no conoce es «Agente desconocido»: ni su id como si fuera un nombre, ni «Disponible»", () => {
  const row = rowOf(
    task("t", { agent_relation: relation("UNKNOWN_AGENT", { assigned_agent_id: "agent-ghost-9", assigned_agent_known: false }) }),
  );
  assert.equal(row.assigned.label, UNKNOWN_AGENT_LABEL);
  assert.equal(UNKNOWN_AGENT_LABEL, "Agente desconocido");
  assert.equal(row.state, "Agente desconocido");
  assert.doesNotMatch(JSON.stringify(row), /Disponible|Operativo/);
});

test("C2 · el agente se llama «desconocido» por lo que dice el BACKEND, no por no estar en la lista que esta pantalla tenga", () => {
  // La lista de agentes no se pudo leer: no se sabe el nombre, pero eso no vuelve «desconocido» a un agente que el backend conoce.
  const row = rowOf(
    task("t", { agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }) }),
    null,
  );
  assert.equal(row.assigned.label, "agent-product-1", "sin lista de agentes se enseña el id tal cual, sin inventar un nombre");
});

// --- D · E · ejecutada por el asignado o por otro -------------------------------------------------------------------------------------------

test("D · ejecutada por el agente asignado: el estado es el de la tarea y no hay desviación", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: "agent-product-1",
      agent_relation: relation("MATCH", {
        assigned_agent_id: "agent-product-1",
        assigned_agent_known: true,
        executed_by_agent_id: "agent-product-1",
        executions: [trace("agent-product-1", { assigned_agent_id: "agent-product-1" })],
      }),
    }),
  );
  assert.equal(row.state, "Completada");
  assert.equal(row.deviation, false);
  assert.equal(row.executedBy?.label, "Product Validation Agent");
});

test("E · ejecutada por un agente DISTINTO del asignado: «Desviación», con los dos agentes a la vista", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: "agent-product-1",
      agent_relation: relation("MISMATCH", {
        assigned_agent_id: "agent-product-1",
        assigned_agent_known: true,
        executed_by_agent_id: "agent-supplier-1",
        executions: [trace("agent-supplier-1", { assigned_agent_id: "agent-product-1" })],
      }),
    }),
  );
  assert.equal(row.state, "Desviación");
  assert.equal(row.deviation, true);
  assert.equal(row.tone, "bad");
  assert.equal(row.assigned.label, "Product Validation Agent");
  assert.equal(row.executedBy?.label, "Supplier Sourcing Agent");
  assert.notEqual(row.assigned.label, row.executedBy?.label, "quién la ejecutó NO se sustituye por quién la tenía asignada");
});

// --- F · G · H · reintentos y reasignaciones -------------------------------------------------------------------------------------------------

test("F · los reintentos se cuentan y se enseñan: el historial no se reduce a la última ejecución", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: "agent-product-1",
      agent_relation: relation("MATCH", {
        assigned_agent_id: "agent-product-1",
        assigned_agent_known: true,
        executed_by_agent_id: "agent-product-1",
        executions: [
          trace("agent-product-1", { attempt: 1, success: false, execution_id: "e-1" }),
          trace("agent-product-1", { attempt: 2, success: true, execution_id: "e-2" }),
        ],
      }),
    }),
  );
  assert.equal(row.attempts, 2);
  assert.equal(row.failedAttempts, 1);
  assert.match(row.note ?? "", /2 intentos/);
});

test("G · un reintento con otro agente se dice: la nota nombra los agentes que lo intentaron", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: "agent-supplier-1",
      agent_relation: relation("MATCH", {
        assigned_agent_id: "agent-supplier-1",
        assigned_agent_known: true,
        executed_by_agent_id: "agent-supplier-1",
        reassigned: true,
        executions: [trace("agent-product-1", { attempt: 1, success: false }), trace("agent-supplier-1", { attempt: 2 })],
      }),
    }),
  );
  assert.match(row.note ?? "", /Product Validation Agent/);
  assert.match(row.note ?? "", /Supplier Sourcing Agent/);
});

test("H · una reasignación se ve, sin ocultar la asignación actual", () => {
  const row = rowOf(
    task("t", {
      status: "PENDING",
      assigned_agent_id: "agent-supplier-1",
      agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-supplier-1", assigned_agent_known: true, reassigned: true }),
    }),
  );
  assert.equal(row.reassigned, true);
  assert.equal(row.assigned.label, "Supplier Sourcing Agent");
  assert.match(row.note ?? "", /reasignada/i);
});

// --- J · inconsistencias, histórico, orquestador ---------------------------------------------------------------------------------------------

test("J · una tarea completada sin rastro de ejecución es «Inconsistente», no «Completada»", () => {
  const row = rowOf(task("t", { status: "COMPLETED", agent_relation: relation("INCONSISTENT") }));
  assert.equal(row.state, "Inconsistente");
  assert.equal(row.tone, "bad");
});

test("N · una tarea anterior al vínculo se dice como lo que es: ejecutada, sin asignación registrada, y no se le inventa una asignación", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: null,
      agent_relation: relation("EXECUTED_UNASSIGNED", { executed_by_agent_id: "agent-product-1", executions: [trace("agent-product-1", { source: "audit", execution_id: null, attempt: null })] }),
    }),
  );
  assert.equal(row.assigned.label, "Sin asignar");
  assert.equal(row.executedBy?.label, "Product Validation Agent");
  assert.equal(row.historical, true);
  assert.match(row.state, /Completada/);
  assert.match(row.state, /sin asignación registrada/);
  assert.equal(row.deviation, false, "no es una desviación: nunca hubo asignación");
});

test("la tarea del orquestador se enseña como del orquestador, no como «Sin asignar» ni con un agente", () => {
  const row = rowOf(task("t", { capability: "decision_synthesis", name: "decision_synthesis", agent_relation: relation("ORCHESTRATOR") }));
  assert.equal(row.assigned.label, "Orquestador (CEO)");
  assert.equal(row.executedBy, null);
  assert.equal(row.state, "Completada");
});

// --- K · M · nada se infiere ---------------------------------------------------------------------------------------------------------------------

test("K · una tarea SIN `agent_relation` (un backend anterior) no se rellena por la capacidad: «No disponible», no el agente de su capacidad", () => {
  const row = rowOf(task("t", { capability: "market_validation" }));
  assert.equal(row.status, "UNAVAILABLE");
  assert.equal(row.assigned.label, TASK_AGENT_UNAVAILABLE_LABEL);
  assert.equal(TASK_AGENT_UNAVAILABLE_LABEL, "No disponible");
  assert.doesNotMatch(JSON.stringify(row), /Product Validation Agent/, "el agente de la capacidad no aparece");
});

test("K2 · una relación con un estado que esta pantalla no conoce es «No disponible»: no se adivina", () => {
  const row = rowOf(task("t", { agent_relation: { ...relation("MATCH"), status: "INVENTED" as AssignmentStatus } }));
  assert.equal(row.status, "UNAVAILABLE");
});

test("K3 · una relación rota (sin ejecuciones como lista, o con tipos que no son) es «No disponible»", () => {
  const broken = [
    { ...relation("MATCH"), executions: null },
    { ...relation("MATCH"), reassigned: "no" },
    { ...relation("MATCH"), assigned_agent_known: "yes" },
    null,
    "MATCH",
  ];
  for (const value of broken) {
    const row = rowOf(task("t", { agent_relation: value as unknown as AgentRelation }));
    assert.equal(row.status, "UNAVAILABLE", JSON.stringify(value));
  }
});

test("M · una ejecución se vincula a su tarea por la relación que manda el backend, no por coincidir en agente o capacidad", () => {
  // Dos tareas de la misma capacidad: cada una enseña SOLO su relación.
  const rows = taskAgentRows(
    [
      task("a", { agent_relation: relation("MATCH", { assigned_agent_id: "agent-product-1", assigned_agent_known: true, executed_by_agent_id: "agent-product-1", executions: [trace("agent-product-1")] }) }),
      task("b", { agent_relation: relation("UNASSIGNED") }),
    ],
    AGENTS,
  );
  assert.equal(rows[0].executedBy?.id, "agent-product-1");
  assert.equal(rows[1].executedBy, null);
  assert.equal(rows[1].assigned.label, "Sin asignar");
});

test("L · un agente eliminado o desconocido en la ejecución no rompe nada: «Agente desconocido»", () => {
  const row = rowOf(
    task("t", {
      assigned_agent_id: "agent-product-1",
      agent_relation: relation("UNKNOWN_AGENT", {
        assigned_agent_id: "agent-product-1",
        assigned_agent_known: true,
        executed_by_agent_id: "agent-removed-3",
        executions: [trace("agent-removed-3", { agent_known: false })],
      }),
    }),
  );
  assert.equal(row.executedBy?.label, UNKNOWN_AGENT_LABEL);
  assert.equal(row.state, "Agente desconocido");
});

// --- por agente --------------------------------------------------------------------------------------------------------------------------------------

test("las tareas de un agente son las que tiene ASIGNADAS o las que EJECUTÓ, nunca las de su capacidad", () => {
  const rows = taskAgentRows(
    [
      task("mine", { assigned_agent_id: "agent-product-1", agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }) }),
      task("ran", { agent_relation: relation("EXECUTED_UNASSIGNED", { executed_by_agent_id: "agent-product-1", executions: [trace("agent-product-1", { source: "audit" })] }) }),
      task("same-capability", { capability: "market_validation", agent_relation: relation("UNASSIGNED") }),
      task("other", { assigned_agent_id: "agent-supplier-1", agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-supplier-1", assigned_agent_known: true }) }),
    ],
    AGENTS,
  );

  assert.deepEqual(agentTaskRows("agent-product-1", rows).map((row) => row.taskId), ["mine", "ran"]);
  assert.deepEqual(agentTaskRows("agent-legal-1", rows), []);
});

test("un agente que ejecutó una tarea ASIGNADA a otro también la ve: la desviación es suya y se le enseña", () => {
  const rows = taskAgentRows(
    [
      task("t", {
        assigned_agent_id: "agent-product-1",
        agent_relation: relation("MISMATCH", {
          assigned_agent_id: "agent-product-1",
          assigned_agent_known: true,
          executed_by_agent_id: "agent-supplier-1",
          executions: [trace("agent-supplier-1")],
        }),
      }),
    ],
    AGENTS,
  );
  assert.deepEqual(agentTaskRows("agent-supplier-1", rows).map((row) => row.taskId), ["t"]);
  assert.deepEqual(agentTaskRows("agent-product-1", rows).map((row) => row.taskId), ["t"]);
});

test("el orden de las filas es el de las tareas que llegan: no se reordena por agente ni por nombre", () => {
  const rows = taskAgentRows([task("z"), task("a"), task("m")], AGENTS);
  assert.deepEqual(rows.map((row) => row.taskId), ["z", "a", "m"]);
});

// --- M49 · Commit 8: fallo, reintento, bloqueo y reasignación ------------------------------------------------------------------------

const recovery = (kind: RecoveryKind, over: Partial<TaskRecovery> = {}): TaskRecovery => ({
  kind,
  can_retry: kind === "recoverable",
  attempts_current_assignment: 1,
  max_attempts_per_assignment: 3,
  attempts_total: 1,
  max_attempts_per_task: 6,
  next_attempt: 2,
  ...over,
});

const failedTrace = (attempt: number, agentId = "agent-product-1") =>
  trace(agentId, { attempt, success: false, assigned_agent_id: agentId, execution_id: `e-${attempt}` });

const MATCHED = (executions: ExecutionTrace[], over: Partial<AgentRelation> = {}) =>
  relation("MATCH", { assigned_agent_id: "agent-product-1", assigned_agent_known: true, executions, ...over });

test("M49 · una tarea fallida con intentos disponibles dice «Fallida · reintento posible» y se pinta en rojo", () => {
  const row = rowOf(task("t", { status: "FAILED", assigned_agent_id: "agent-product-1", agent_relation: MATCHED([failedTrace(1)]), recovery: recovery("recoverable") }));
  assert.equal(row.state, "Fallida · reintento posible");
  assert.equal(row.tone, "bad");
  assert.equal(row.recoveryKind, "recoverable");
  assert.equal(row.failedAttempts, 1);
});

test("M49 · un agente que gastó sus intentos pide reasignación y un fallo definitivo se dice definitivo (no se pide reintentar)", () => {
  const executions = [failedTrace(1), failedTrace(2), failedTrace(3)];
  const base = { status: "FAILED" as const, assigned_agent_id: "agent-product-1", agent_relation: MATCHED(executions) };
  assert.equal(rowOf(task("a", { ...base, recovery: recovery("reassign_required") })).state, "Fallida · requiere reasignación");
  assert.equal(rowOf(task("b", { ...base, recovery: recovery("definitive") })).state, "Fallida · definitiva");
});

test("M49 · una tarea fallida de un backend que aún no envía `recovery` sigue diciendo solo «Fallida»", () => {
  const row = rowOf(task("t", { status: "FAILED", agent_relation: MATCHED([failedTrace(1)]) }));
  assert.equal(row.state, "Fallida");
  assert.equal(row.recoveryKind, null);
});

test("M49 · una tarea pendiente que ya tuvo un intento fallido es «Reintentando»; una que nunca se ejecutó, «Pendiente»", () => {
  const retrying = rowOf(task("a", { status: "PENDING", agent_relation: MATCHED([failedTrace(1)]) }));
  assert.equal(retrying.state, "Reintentando");
  const waiting = rowOf(task("b", { status: "PENDING", agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }) }));
  assert.equal(waiting.state, "Pendiente");
});

test("M49 · una tarea bloqueada dice «Bloqueada» (no «Pendiente») y se pinta en ámbar; el agente desconocido manda sobre el bloqueo", () => {
  const blocked = rowOf(
    task("a", {
      status: "BLOCKED",
      agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-supplier-1", assigned_agent_known: true }),
      recovery: recovery("blocked", { attempts_current_assignment: 0, attempts_total: 0, next_attempt: 1 }),
    }),
  );
  assert.equal(blocked.state, "Bloqueada");
  assert.equal(blocked.tone, "warn");
  const unknown = rowOf(
    task("b", {
      status: "BLOCKED",
      assigned_agent_id: "agent-ghost-9",
      agent_relation: relation("UNKNOWN_AGENT", { assigned_agent_id: "agent-ghost-9", assigned_agent_known: false }),
      recovery: recovery("unknown_agent"),
    }),
  );
  assert.equal(unknown.state, UNKNOWN_AGENT_LABEL);
  assert.equal(unknown.tone, "bad");
});

test("M49 · tras una reasignación el agente asignado es el nuevo, el que ejecutó sigue siendo el anterior, y se dice «Reasignada»", () => {
  const row = rowOf(
    task("t", {
      status: "FAILED",
      assigned_agent_id: "agent-supplier-1",
      agent_relation: relation("ASSIGNED", {
        assigned_agent_id: "agent-supplier-1",
        assigned_agent_known: true,
        reassigned: true,
        executions: [failedTrace(1), failedTrace(2)],
      }),
      recovery: recovery("recoverable", { attempts_current_assignment: 0, attempts_total: 2, next_attempt: 3 }),
    }),
  );
  assert.equal(row.assigned.label, "Supplier Sourcing Agent");
  assert.equal(row.executedBy?.label, "Product Validation Agent");
  assert.match(row.note ?? "", /Reasignada/);
  assert.match(row.note ?? "", /2 intentos \(2 fallidos\)/);
  assert.equal(row.deviation, false);
});

test("M49 · una desviación sigue diciendo «Desviación» aunque la tarea haya fallado", () => {
  const deviant = trace("agent-supplier-1", { attempt: 1, success: false, assigned_agent_id: "agent-product-1" });
  const row = rowOf(task("t", { status: "FAILED", assigned_agent_id: "agent-product-1", agent_relation: relation("MISMATCH", { assigned_agent_id: "agent-product-1", assigned_agent_known: true, executions: [deviant] }), recovery: recovery("mismatch") }));
  assert.equal(row.state, "Desviación");
  assert.equal(row.deviation, true);
});

test("M49 · `recoveryOf` solo acepta el contrato completo: un tipo desconocido, un recuento negativo o un campo que falta es «sin dato»", () => {
  assert.equal(recoveryOf(task("a", { recovery: recovery("recoverable") }))?.kind, "recoverable");
  assert.equal(recoveryOf(task("b")), null);
  assert.equal(recoveryOf(task("c", { recovery: { ...recovery("recoverable"), kind: "retry_now" as never } })), null);
  assert.equal(recoveryOf(task("d", { recovery: { ...recovery("recoverable"), attempts_total: -1 } })), null);
  assert.equal(recoveryOf(task("e", { recovery: { ...recovery("recoverable"), can_retry: "yes" as never } })), null);
  assert.equal(recoveryOf(task("f", { recovery: { kind: "none" } as never })), null);
});

test("M49 · la fila no inventa un reintento ni una reasignación: sin `recovery` válido solo cuenta lo que dice la relación", () => {
  const row = rowOf(task("t", { status: "FAILED", recovery: { ...recovery("recoverable"), kind: "retry_now" as never }, agent_relation: MATCHED([failedTrace(1)]) }));
  assert.equal(row.state, "Fallida");
  assert.equal(row.recoveryKind, null);
});
