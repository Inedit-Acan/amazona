import type { Job, JobStatus } from "./api.ts";

// Vista del runtime de trabajos para el panel Estado (Milestone 31).
//
// A diferencia de casi todo lo demás de esta pantalla, aquí NO hay datos de
// demostración: o el backend responde la cola, o no se enseña nada. Una cola
// inventada diría que el sistema está trabajando cuando no lo está, que es
// exactamente la clase de mentira que el plan maestro prohíbe.

/** Estados agrupados por lo que significan para quien mira el panel. */
export const ACTIVE_STATUSES: JobStatus[] = ["QUEUED", "RUNNING", "RETRYING", "PENDING"];
export const HELD_STATUSES: JobStatus[] = ["WAITING_APPROVAL", "BLOCKED"];
export const FINISHED_STATUSES: JobStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];

export interface JobCounts {
  pending: number;
  queued: number;
  running: number;
  retrying: number;
  waitingApproval: number;
  blocked: number;
  completed: number;
  failed: number;
  cancelled: number;
}

const EMPTY: JobCounts = {
  pending: 0,
  queued: 0,
  running: 0,
  retrying: 0,
  waitingApproval: 0,
  blocked: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
};

const KEY: Record<JobStatus, keyof JobCounts> = {
  PENDING: "pending",
  QUEUED: "queued",
  RUNNING: "running",
  RETRYING: "retrying",
  WAITING_APPROVAL: "waitingApproval",
  BLOCKED: "blocked",
  COMPLETED: "completed",
  FAILED: "failed",
  CANCELLED: "cancelled",
};

export function jobCounts(jobs: Job[]): JobCounts {
  const counts = { ...EMPTY };
  for (const job of jobs) {
    const key = KEY[job.status];
    if (key) counts[key] += 1;
  }
  return counts;
}

/** Trabajos que el runtime va a tocar por su cuenta. */
export function activeCount(counts: JobCounts): number {
  return counts.pending + counts.queued + counts.running + counts.retrying;
}

/** Trabajos parados esperando a una persona o a una condición: el runtime no
 * los va a mover solo, así que es lo que de verdad hay que mirar. */
export function heldCount(counts: JobCounts): number {
  return counts.waitingApproval + counts.blocked;
}

export interface QueueVerdict {
  tone: "ok" | "warning" | "error";
  headline: string;
  detail: string;
}

/** Qué decir del runtime en una línea.
 *
 * Un fallo pesa más que una cola larga: una cola con trabajo es un sistema
 * ocupado, pero un trabajo agotado es trabajo que nadie va a terminar salvo que
 * alguien lo reencole. */
export function queueVerdict(counts: JobCounts, workerSeen: boolean): QueueVerdict {
  if (counts.failed > 0) {
    return {
      tone: "error",
      headline: `${counts.failed} ${counts.failed === 1 ? "trabajo agotado" : "trabajos agotados"}`,
      detail: "Agotaron sus intentos. No se reintentarán solos: hay que reencolarlos.",
    };
  }
  if (heldCount(counts) > 0) {
    return {
      tone: "warning",
      headline: `${heldCount(counts)} en espera de decisión`,
      detail: "Parados hasta que alguien apruebe o se levante el bloqueo.",
    };
  }
  if (activeCount(counts) > 0 && !workerSeen) {
    return {
      tone: "warning",
      headline: "Hay trabajo en cola y ningún worker lo ha tocado",
      detail: "Comprueba que haya un worker vivo: python -m app.jobs.worker",
    };
  }
  if (activeCount(counts) > 0) {
    return { tone: "ok", headline: `${activeCount(counts)} en curso`, detail: "El runtime está trabajando." };
  }
  return { tone: "ok", headline: "Cola vacía", detail: "Nada pendiente de ejecutar." };
}

export interface JobRow {
  id: string;
  type: string;
  status: JobStatus;
  attempts: string;
  /** Instante que hay que enseñar según el estado: cuándo terminó, o desde
   * cuándo espera. */
  at: number;
  error: string | null;
}

/** Un trabajo ha sido tocado por un worker si llegó a empezar alguna vez. */
export function workerSeen(jobs: Job[]): boolean {
  return jobs.some((job) => job.started_at !== null);
}

export function jobRows(jobs: Job[], limit = 8): JobRow[] {
  return jobs.slice(0, limit).map((job) => ({
    id: job.id,
    type: job.type,
    status: job.status,
    attempts: `${job.attempt}/${job.max_attempts}`,
    at: new Date(job.completed_at ?? job.failed_at ?? job.started_at ?? job.created_at).getTime(),
    error: job.error,
  }));
}
