// La salud del backend que enseña la cabecera (M47, Commit 1).
//
// Antes la cabecera decía «Sistema operativo» con un punto verde fijo: no consultaba nada. Ahora el estado sale de
// `GET /health/ready`, y la cabecera dice solo lo que ese endpoint puede demostrar.
//
// CONTRATO de `/health/ready` (backend/app/main.py, `health_ready`; público, sin token, sin detalle):
//   200  {"status": "ok"}        el proceso atiende y alcanza su base de datos (`SELECT 1`).
//   503  {"status": "degraded"}  el proceso atiende pero NO alcanza su base de datos.
//   cualquier otra cosa (sin respuesta, timeout, 5xx distinto, 404, cuerpo que no es ese JSON) = no se pudo demostrar.
//
// Lo que NO demuestra: que los agentes estén bien, que los proveedores respondan, que el negocio esté operativo ni nada
// de los servicios externos. Por eso la etiqueta dice «Backend», nunca «Sistema».
//
// No es `ReadState` ni `AgentStatus` (ver lib/agent-status.ts): es el veredicto de una comprobación.

export type HealthVerdict = "ready" | "degraded" | "unavailable";

/** Lo que devolvió la petición, sin interpretar. */
export interface ReadinessReply {
  status: number;
  body: unknown;
}

/** Interpreta la respuesta de `/health/ready`. Solo `200 + {"status":"ok"}` es `ready` y solo `503 + {"status":"degraded"}`
 * es `degraded`: cualquier otra combinación NO se acepta como «bien» —un 200 con un cuerpo inesperado es un contrato roto,
 * no una confirmación. */
export function classifyReadiness(reply: ReadinessReply): HealthVerdict {
  const status = typeof reply.body === "object" && reply.body !== null && "status" in reply.body ? (reply.body as { status: unknown }).status : null;
  if (reply.status === 200 && status === "ok") return "ready";
  if (reply.status === 503 && status === "degraded") return "degraded";
  return "unavailable";
}

/** Techo de una comprobación. DEBE superar el `connect_timeout` de la base de datos del backend (5 s, `backend/app/db/session.py`):
 * con la BD caída `/health/ready` tarda ~5 s en contestar su 503 `degraded`, y un techo menor lo confundiría con «sin
 * respuesta» (medido en M47: 5,07 s). Un test lee ese valor del backend y exige que este techo lo supere. Un backend que
 * ni escucha falla al instante (conexión rechazada), así que el techo largo solo se nota con un servidor colgado. */
export const HEALTH_TIMEOUT_MS = 8_000;
export const HEALTH_POLL_MS = 60_000;
/** Entre dos comprobaciones disparadas por «volver a la pestaña» y «recuperar el foco» (que suelen llegar juntas). */
export const HEALTH_MIN_GAP_MS = 5_000;

/** Una comprobación completa: nunca lanza y nunca se queda colgada. Un rechazo, un timeout o un cuerpo ilegible son
 * `unavailable`. `fetchReply` recibe una señal para cancelar, pero el timeout no depende de que la respete. */
export async function checkBackend(
  fetchReply: (signal: AbortSignal) => Promise<ReadinessReply>,
  timeoutMs: number = HEALTH_TIMEOUT_MS,
): Promise<HealthVerdict> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<HealthVerdict>((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve("unavailable");
    }, timeoutMs);
  });
  const request = fetchReply(controller.signal).then(classifyReadiness, (): HealthVerdict => "unavailable");
  try {
    return await Promise.race([request, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

// --- Estado que enseña la cabecera --------------------------------------------------------------------------------

/** `checking`: aún no hay ninguna comprobación terminada. NUNCA se enseña como «operativo».
 * `known`: hay un veredicto; con `refreshing` hay una consulta nueva en vuelo y el veredicto es el ANTERIOR (se dice). */
export type BackendHealthState =
  | { kind: "checking" }
  | { kind: "known"; verdict: HealthVerdict; checkedAt: number; refreshing: boolean };

export const INITIAL_HEALTH: BackendHealthState = { kind: "checking" };

export const HEALTH_LABEL: Record<HealthVerdict, string> = {
  ready: "Backend operativo",
  degraded: "Backend degradado",
  unavailable: "Backend no disponible",
};

export const CHECKING_LABEL = "Comprobando backend…";

/** El texto visible de la cabecera. */
export function healthLabel(state: BackendHealthState): string {
  return state.kind === "checking" ? CHECKING_LABEL : HEALTH_LABEL[state.verdict];
}

/** Lo que el veredicto demuestra y lo que no; es el `title` de la cabecera. */
export const HEALTH_SCOPE_NOTE =
  "Solo indica si el backend responde y alcanza su base de datos. No comprueba los agentes, los proveedores ni los servicios externos.";

// --- Monitor: una sola petición activa, disparadores acotados -----------------------------------------------------

export type HealthTrigger = "mount" | "visible" | "focus" | "poll";

export interface HealthScheduler {
  setInterval(handler: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

export interface HealthMonitorOptions {
  /** La comprobación (en producción, `checkBackend` sobre `api.getReadiness`). */
  check: () => Promise<HealthVerdict>;
  now: () => number;
  onChange: (state: BackendHealthState) => void;
  scheduler?: HealthScheduler;
  pollMs?: number;
  minGapMs?: number;
}

const DEFAULT_SCHEDULER: HealthScheduler = {
  setInterval: (handler, ms) => setInterval(handler, ms),
  clearInterval: (handle) => clearInterval(handle as ReturnType<typeof setInterval>),
};

/** Reglas (M47 · P3):
 *  - Una única petición activa: si hay una en vuelo, un disparador nuevo se ignora.
 *  - Disparadores: al montar, al volver la pestaña a visible, al recuperar el foco y cada `pollMs` SOLO mientras la
 *    pestaña está visible. Con la pestaña oculta no hay temporizador ni peticiones.
 *  - «Volver a visible» y «recuperar el foco» llegan juntos: se ignoran si la anterior empezó hace menos de `minGapMs`.
 *  - Un fallo es `unavailable`; el último veredicto bueno NO se conserva en silencio. Mientras una consulta nueva está en
 *    vuelo se mantiene el veredicto anterior marcado `refreshing`, para no confundirlo con uno ya confirmado.
 *  - `dispose` cancela el temporizador y descarta cualquier respuesta que llegue después. */
export class HealthMonitor {
  private readonly options: HealthMonitorOptions;
  private readonly scheduler: HealthScheduler;
  private readonly pollMs: number;
  private readonly minGapMs: number;
  private state: BackendHealthState = INITIAL_HEALTH;
  private inFlight = false;
  private disposed = false;
  private visible = false;
  private lastStartedAt: number | null = null;
  private timer: unknown = null;

  constructor(options: HealthMonitorOptions) {
    this.options = options;
    this.scheduler = options.scheduler ?? DEFAULT_SCHEDULER;
    this.pollMs = options.pollMs ?? HEALTH_POLL_MS;
    this.minGapMs = options.minGapMs ?? HEALTH_MIN_GAP_MS;
  }

  get current(): BackendHealthState {
    return this.state;
  }

  /** Arranca con la visibilidad actual de la pestaña. */
  start(visible: boolean): void {
    this.visible = visible;
    if (visible) {
      this.trigger("mount");
      this.startPolling();
    }
  }

  /** La pestaña pasó a visible u oculta. */
  setVisible(visible: boolean): void {
    if (this.disposed || visible === this.visible) return;
    this.visible = visible;
    if (visible) {
      this.trigger("visible");
      this.startPolling();
    } else {
      this.stopPolling();
    }
  }

  /** La ventana recuperó el foco. */
  focus(): void {
    if (this.visible) this.trigger("focus");
  }

  dispose(): void {
    this.disposed = true;
    this.stopPolling();
  }

  /** Lanza una comprobación si procede. Devuelve true si la lanzó. */
  trigger(reason: HealthTrigger): boolean {
    if (this.disposed || this.inFlight) return false;
    const at = this.options.now();
    const soonAfterAnother = this.lastStartedAt !== null && at - this.lastStartedAt < this.minGapMs;
    if ((reason === "visible" || reason === "focus") && soonAfterAnother) return false;

    this.inFlight = true;
    this.lastStartedAt = at;
    if (this.state.kind === "known") this.emit({ ...this.state, refreshing: true });
    void this.options.check().catch((): HealthVerdict => "unavailable").then((verdict) => {
      this.inFlight = false;
      if (this.disposed) return;
      this.emit({ kind: "known", verdict, checkedAt: this.options.now(), refreshing: false });
    });
    return true;
  }

  private emit(next: BackendHealthState): void {
    this.state = next;
    this.options.onChange(next);
  }

  private startPolling(): void {
    if (this.timer !== null || this.disposed) return;
    this.timer = this.scheduler.setInterval(() => this.trigger("poll"), this.pollMs);
  }

  private stopPolling(): void {
    if (this.timer === null) return;
    this.scheduler.clearInterval(this.timer);
    this.timer = null;
  }
}
