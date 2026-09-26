import assert from "node:assert/strict";
import { test } from "node:test";
import type { PipelineRun, PipelineRunStatus, PipelineStep, PipelineStepStatus } from "./api.ts";
import {
  STEP_ORDER,
  deniedSteps,
  pipelineCounts,
  pipelineRunRows,
  pipelineVerdict,
  runError,
  stepProgress,
} from "./pipeline-view.ts";

function step(step_status: PipelineStepStatus, over: Partial<PipelineStep> = {}): PipelineStep {
  return {
    correlation_id: "cid-step",
    entity_id: step_status === "COMPLETED" ? "entity-1" : undefined,
    step_status,
    attempt: step_status === "PENDING" ? 0 : 1,
    ...over,
  };
}

/** Una ejecución con los `completed` primeros pasos terminados. */
function run(status: PipelineRunStatus, completed: number, over: Partial<PipelineRun> = {}): PipelineRun {
  const steps: Record<string, PipelineStep> = {};
  STEP_ORDER.forEach((name, index) => {
    steps[name] = step(index < completed ? "COMPLETED" : "PENDING");
  });
  return {
    correlation_id: `corr-${status}-${completed}`,
    product_id: completed > 0 ? "prod-1" : null,
    category: "home",
    market: "us",
    status,
    failed_step: null,
    needs_review: false,
    steps,
    job_id: "job-1",
    ...over,
  };
}

test("pipelineCounts reparte cada estado en su casilla", () => {
  const counts = pipelineCounts([
    run("QUEUED", 0),
    run("RUNNING", 3),
    run("COMPLETED", 9),
    run("COMPLETED", 9, { correlation_id: "otra" }),
    run("PARTIAL", 1),
    run("FAILED", 2),
    run("BLOCKED", 0),
    run("CANCELLED", 4),
  ]);

  assert.deepEqual(counts, {
    queued: 1,
    running: 1,
    completed: 2,
    partial: 1,
    failed: 1,
    blocked: 1,
    cancelled: 1,
    waitingApproval: 0,
  });
});

test("pipelineCounts cuenta lo que espera una autorización", () => {
  const counts = pipelineCounts([run("WAITING_APPROVAL", 4), run("COMPLETED", 9)]);

  assert.equal(counts.waitingApproval, 1);
});

test("stepProgress cuenta los pasos terminados y señala por dónde va", () => {
  const progress = stepProgress(run("RUNNING", 4));

  assert.equal(progress.completed, 4);
  assert.equal(progress.total, 9);
  assert.equal(progress.current, "ecommerce");
  assert.equal(progress.currentStatus, "PENDING");
});

test("stepProgress prefiere el paso que se está ejecutando", () => {
  const value = run("RUNNING", 2);
  value.steps.economics = step("RUNNING");

  const progress = stepProgress(value);

  assert.equal(progress.current, "economics");
  assert.equal(progress.currentStatus, "RUNNING");
});

test("stepProgress de una ejecución terminada no señala ningún paso", () => {
  const progress = stepProgress(run("COMPLETED", 9));

  assert.equal(progress.completed, 9);
  assert.equal(progress.current, null);
});

test("stepProgress señala el paso fallido de una ejecución parada", () => {
  const value = run("FAILED", 2, { failed_step: "economics" });
  value.steps.economics = step("FAILED", { error: "RuntimeError: provider is down" });

  const progress = stepProgress(value);

  assert.equal(progress.completed, 2);
  assert.equal(progress.current, "economics");
  assert.equal(progress.currentStatus, "FAILED");
});

test("runError saca el error del paso que dejó la ejecución parada", () => {
  const value = run("FAILED", 2, { failed_step: "economics" });
  value.steps.economics = step("FAILED", { error: "RuntimeError: provider is down" });

  assert.equal(runError(value), "RuntimeError: provider is down");
  assert.equal(runError(run("COMPLETED", 9)), null);
});

test("pipelineRunRows resume cada ejecución y respeta el tope", () => {
  const rows = pipelineRunRows([run("RUNNING", 3), run("COMPLETED", 9), run("QUEUED", 0)], 2);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].status, "RUNNING");
  assert.equal(rows[0].progress.completed, 3);
  assert.equal(rows[0].category, "home");
  assert.equal(rows[0].jobId, "job-1");
});

test("una ejecución bloqueada pesa más que cualquier otra cosa", () => {
  const verdict = pipelineVerdict(
    pipelineCounts([run("BLOCKED", 0), run("RUNNING", 2), run("FAILED", 1), run("COMPLETED", 9)]),
  );

  assert.equal(verdict.tone, "error");
  assert.match(verdict.headline, /bloqueada/);
  assert.match(verdict.detail, /kill switch/);
});

test("un paso fallido avisa, pero dice que el runtime lo reintenta solo", () => {
  const verdict = pipelineVerdict(pipelineCounts([run("FAILED", 2), run("COMPLETED", 9)]));

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.detail, /reintentan solas/);
});

test("una ejecución incompleta manda a la bandeja de revisión", () => {
  const verdict = pipelineVerdict(pipelineCounts([run("PARTIAL", 1)]));

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.headline, /incompleta/);
});

test("con trabajo en curso y nada parado, el veredicto es tranquilo", () => {
  const verdict = pipelineVerdict(pipelineCounts([run("RUNNING", 3), run("QUEUED", 0)]));

  assert.equal(verdict.tone, "ok");
  assert.equal(verdict.headline, "2 en curso");
});

test("una cancelación no se confunde con un fallo: nadie la va a continuar", () => {
  const verdict = pipelineVerdict(pipelineCounts([run("CANCELLED", 4), run("COMPLETED", 9)]));

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.detail, /No vuelven solas/);
});

test("sin ejecuciones no se inventa nada", () => {
  const verdict = pipelineVerdict(pipelineCounts([]));

  assert.equal(verdict.tone, "ok");
  assert.equal(verdict.headline, "Sin ejecuciones");
});

// --- El ActionGate (Milestone 33) ------------------------------------------

test("esperar una autorización pesa más que cualquier otra cosa: nadie más lo va a mover", () => {
  const verdict = pipelineVerdict(
    pipelineCounts([run("WAITING_APPROVAL", 4), run("BLOCKED", 0), run("FAILED", 2)]),
  );

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.headline, /espera autorización/);
  assert.match(verdict.detail, /Aprobaciones/);
});

test("deniedSteps nombra los pasos que el gate no dejó ejecutar", () => {
  const value = run("COMPLETED", 9);
  value.steps.marketing = step("DENIED", { error: "legal recommendation is NO_GO" });
  value.steps.marketplace = step("DENIED");

  assert.deepEqual(deniedSteps(value), ["marketplace", "marketing"]);
});

test("una ejecución sin nada denegado no inventa denegaciones", () => {
  assert.deepEqual(deniedSteps(run("COMPLETED", 9)), []);
});

test("pipelineRunRows lleva las denegaciones a la fila", () => {
  const value = run("COMPLETED", 9);
  value.steps.marketing = step("DENIED", { error: "legal recommendation is NO_GO" });

  const [row] = pipelineRunRows([value]);

  assert.deepEqual(row.denied, ["marketing"]);
  assert.equal(row.error, "legal recommendation is NO_GO");
});

test("stepProgress señala el paso que espera autorización", () => {
  const value = run("WAITING_APPROVAL", 4);
  value.steps.ecommerce = step("WAITING_APPROVAL");

  const progress = stepProgress(value);

  assert.equal(progress.current, "ecommerce");
  assert.equal(progress.currentStatus, "WAITING_APPROVAL");
  assert.equal(progress.completed, 4);
});
