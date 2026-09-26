import assert from "node:assert/strict";
import { test } from "node:test";
import type { Job, JobStatus } from "./api.ts";
import { activeCount, heldCount, jobCounts, jobRows, queueVerdict, workerSeen } from "./jobs-view.ts";

const BASE = "2026-09-26T10:00:00Z";

function job(status: JobStatus, over: Partial<Job> = {}): Job {
  return {
    id: over.id ?? `job-${status}-${Math.random().toString(36).slice(2, 8)}`,
    type: "diagnostic.echo",
    status,
    payload: {},
    correlation_id: "corr-1",
    attempt: 0,
    max_attempts: 3,
    available_at: BASE,
    created_at: BASE,
    started_at: null,
    completed_at: null,
    failed_at: null,
    cancelled_at: null,
    error: null,
    result_reference: null,
    created_by: null,
    ...over,
  };
}

test("jobCounts reparte cada estado en su casilla", () => {
  const counts = jobCounts([job("QUEUED"), job("QUEUED"), job("RUNNING"), job("FAILED")]);

  assert.equal(counts.queued, 2);
  assert.equal(counts.running, 1);
  assert.equal(counts.failed, 1);
  assert.equal(counts.completed, 0);
});

test("activo es lo que el runtime va a mover solo", () => {
  const counts = jobCounts([job("PENDING"), job("QUEUED"), job("RUNNING"), job("RETRYING"), job("COMPLETED")]);

  assert.equal(activeCount(counts), 4);
});

test("en espera es lo que NO se moverá solo", () => {
  const counts = jobCounts([job("WAITING_APPROVAL"), job("BLOCKED"), job("QUEUED")]);

  assert.equal(heldCount(counts), 2);
});

test("un trabajo agotado pesa más que una cola larga", () => {
  const verdict = queueVerdict(jobCounts([job("FAILED"), ...Array(20).fill(null).map(() => job("QUEUED"))]), true);

  assert.equal(verdict.tone, "error");
  assert.match(verdict.headline, /agotado/);
  assert.match(verdict.detail, /reencolar/);
});

test("lo parado a la espera de una persona se avisa aunque no haya fallos", () => {
  const verdict = queueVerdict(jobCounts([job("WAITING_APPROVAL")]), true);

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.headline, /decisión/);
});

test("cola con trabajo y ningún worker que la haya tocado es un aviso", () => {
  const jobs = [job("QUEUED"), job("QUEUED")];

  const verdict = queueVerdict(jobCounts(jobs), workerSeen(jobs));

  assert.equal(verdict.tone, "warning");
  assert.match(verdict.detail, /app\.jobs\.worker/);
});

test("la misma cola con un worker que sí trabajó es normalidad", () => {
  const jobs = [job("QUEUED"), job("COMPLETED", { started_at: BASE, completed_at: BASE })];

  const verdict = queueVerdict(jobCounts(jobs), workerSeen(jobs));

  assert.equal(verdict.tone, "ok");
  assert.match(verdict.headline, /en curso/);
});

test("cola vacía se dice tal cual", () => {
  const verdict = queueVerdict(jobCounts([]), false);

  assert.equal(verdict.tone, "ok");
  assert.equal(verdict.headline, "Cola vacía");
});

test("workerSeen distingue una cola sin tocar de una que ya se ejecutó", () => {
  assert.equal(workerSeen([job("QUEUED")]), false);
  assert.equal(workerSeen([job("RUNNING", { started_at: BASE })]), true);
});

test("cada fila enseña el instante que le corresponde a su estado", () => {
  const completed = "2026-09-26T11:00:00Z";
  const rows = jobRows([
    job("COMPLETED", { id: "a", started_at: BASE, completed_at: completed }),
    job("QUEUED", { id: "b" }),
  ]);

  assert.equal(rows[0].at, new Date(completed).getTime());
  assert.equal(rows[1].at, new Date(BASE).getTime());
});

test("las filas dicen los intentos gastados sobre el máximo", () => {
  const [row] = jobRows([job("RETRYING", { attempt: 2, max_attempts: 5 })]);

  assert.equal(row.attempts, "2/5");
});

test("jobRows respeta el límite pedido", () => {
  const rows = jobRows(Array(20).fill(null).map(() => job("QUEUED")), 5);

  assert.equal(rows.length, 5);
});
