import assert from "node:assert/strict";
import { test } from "node:test";
import type { TaskStatus } from "./api.ts";
import { pipelineSteps, projectRisks, projectedFinance, taskProgress } from "./projects.ts";

const task = (name: string, status: TaskStatus) => ({ name, status });

test("taskProgress: completadas sobre el total y 0 sin tareas", () => {
  assert.deepEqual(taskProgress([task("a", "COMPLETED"), task("b", "COMPLETED"), task("c", "PENDING"), task("d", "RUNNING")]), {
    done: 2,
    total: 4,
    ratio: 0.5,
  });
  assert.deepEqual(taskProgress([]), { done: 0, total: 0, ratio: 0 });
});

test("pipelineSteps: estado por fase desde el grafo y recomendación desde la evidencia", () => {
  const steps = pipelineSteps(
    [
      task("product_validation", "COMPLETED"),
      task("supplier_sourcing", "RUNNING"),
      task("finance_validation", "FAILED"),
      // legal_validation ausente
    ],
    {
      evidence: [
        { source: "product_validation", summary: "GO", data: { recommendation: "GO" } },
        { source: "supplier_sourcing", summary: "x", data: null },
      ],
    },
  );
  assert.deepEqual(
    steps.map((s) => [s.label, s.state, s.recommendation]),
    [
      ["Investigación", "done", "GO"],
      ["Proveedores", "current", null],
      ["Economía", "blocked", null],
      ["Legal", "todo", null],
    ],
  );
  assert.equal(steps[0].href, "/research");
  assert.deepEqual(pipelineSteps([], null).map((s) => s.state), ["todo", "todo", "todo", "todo"]);
});

test("projectRisks recoge los riesgos de cada especialista con su fase", () => {
  const risks = projectRisks({
    evidence: [
      { source: "product_validation", summary: "REVIEW", data: { risks: ["insufficient market data"] } },
      { source: "legal_validation", summary: "ok", data: { risks: [] } },
      { source: "otro", summary: "?", data: { risks: ["algo", 3] } },
    ],
  });
  assert.deepEqual(risks, [
    { stage: "Investigación", risk: "insufficient market data" },
    { stage: "otro", risk: "algo" },
  ]);
  assert.deepEqual(projectRisks(null), []);
});

test("projectedFinance lee monthly_profit y margin de la evidencia de finanzas, o null", () => {
  assert.deepEqual(
    projectedFinance({
      evidence: [{ source: "finance_validation", summary: "margin 75.00%", data: { margin: 0.75, monthly_profit: 4000, recommendation: "GO" } }],
    }),
    { monthlyProfit: 4000, margin: 0.75 },
  );
  assert.deepEqual(
    projectedFinance({ evidence: [{ source: "finance_validation", summary: "x", data: { monthly_profit: -20 } }] }),
    { monthlyProfit: -20, margin: null },
  );
  assert.equal(projectedFinance({ evidence: [{ source: "finance_validation", summary: "x", data: { recommendation: "REVIEW" } }] }), null);
  assert.equal(projectedFinance({ evidence: [] }), null);
  assert.equal(projectedFinance(null), null);
});
