/** Identidad de intención: una `Idempotency-Key` por cosa que la persona quiere hacer (Milestone 44, ADR 0025 y 0028 §9).
 *
 * `lib/idempotency.ts` pone una clave nueva en cada llamada. Eso cumple la exigencia del backend, pero no protege de
 * nada: un segundo clic, un reintento tras un timeout o una respuesta perdida son **otra llamada con otra clave**, y el
 * backend, que identifica la petición por su clave, las ejecuta las dos. Este módulo decide cuándo dos llamadas son la
 * **misma intención** y, solo entonces, les da la misma clave.
 *
 * Una intención es `operación + objetivo + parámetros canónicos`:
 *
 * - la **operación** y el **objetivo** (el recurso sobre el que se actúa) eligen la *ranura*; en una ranura hay a lo
 *   sumo una intención viva, y ranuras distintas nunca comparten clave (dos formularios, o dos pedidos, no se pisan);
 * - los **parámetros**, serializados de forma canónica, dicen si es *la misma* intención de esa ranura: si cambian de
 *   verdad la clave es otra, y si solo cambia el orden de los campos o un rerender no cambia nada.
 *
 * Qué conserva la clave y qué la cambia (las cinco filas son el contrato que prueba `intent-key.test.ts`):
 *
 *     en vuelo (mismo clic otra vez)          misma clave y **la misma promesa**: no se envía una segunda petición
 *     timeout · red caída · 5xx · 408/425/429 misma clave (no se sabe si llegó)
 *     409 «en curso» del backend              misma clave (ya se está procesando: esperar, nunca otra clave)
 *     resultado desconocido                   misma clave, **y no se da por terminada**: ni el 409
 *                                             `idempotency_outcome_unknown` ni un 200 con `UNKNOWN_OUTCOME`
 *     rechazo definitivo (400/404/409 de      misma clave: el backend la libera cuando nada se hizo, y reutilizarla
 *     negocio/422)                            es lo mismo que una intención nueva con los mismos datos
 *     éxito                                   se acaba la intención: la siguiente acción deliberada, otra clave
 *     cambian operación, objetivo o parámetros   otra clave
 *
 * **No hay caducidad por tiempo.** El backend tampoco la tiene (`app/idempotency/service.py`): «hace mucho» no significa
 * «no ocurrió». Una intención ambigua dura mientras dure la pestaña (se guarda en `sessionStorage`, no en
 * `localStorage`) o hasta que una persona decida, con `discard`, que ya comprobó qué pasó y empieza otra.
 *
 * La clave es opaca (un UUID): no lleva ni deriva de la operación, el objetivo ni los parámetros. Lo que se guarda en la
 * pestaña es la huella de los parámetros, nunca los parámetros, para que un dato personal de un formulario no se quede
 * en el almacenamiento. Sin dependencias del navegador ni de React: se prueba con `node --test`. */

import { newIdempotencyKey } from "./idempotency.ts";

export type IntentPhase = "idle" | "in_flight" | "retryable" | "unknown" | "rejected";

/** Qué le pasó a una intención que no terminó bien. */
export type FailureKind = "retryable" | "unknown" | "rejected" | "conflict";

export interface IntentSpec {
  /** Qué se hace: un identificador estable, p. ej. `fulfillment.purchase`. */
  operation: string;
  /** Sobre qué: el identificador opaco del recurso (un id). Nunca texto libre ni un dato personal. */
  target: string;
  /** Con qué parámetros. Cualquier valor serializable; el orden de los campos no importa. */
  params?: unknown;
}

export interface IntentStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** `done`: la operación terminó y la intención se cierra. `unknown`: la respuesta llegó pero no dice si hubo efecto. */
export type Verdict = "done" | "unknown";

const SAFE_TOKEN = /^[A-Za-z0-9._:\-/]{1,128}$/;
const STORAGE_PREFIX = "amazona.intent.v1";

// --- Parámetros canónicos ---------------------------------------------------------------------------------------

function normalise(value: unknown): unknown {
  if (value === null || typeof value !== "object") {
    if (typeof value === "bigint") return value.toString();
    return value;
  }
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return value.map((item) => (item === undefined ? null : normalise(item)));
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, field]) => field !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, field]) => [name, normalise(field)] as const);
  return Object.fromEntries(entries);
}

/** La serialización estable de unos parámetros: mismo contenido, mismo texto, sea cual sea el orden de los campos.
 * Un campo `undefined` es lo mismo que uno ausente; un `null`, no. */
export function canonicalize(value: unknown): string {
  return JSON.stringify(normalise(value)) ?? "null";
}

function assertSafe(label: string, value: string): void {
  if (!SAFE_TOKEN.test(value)) {
    throw new TypeError(
      `${label} must be an opaque identifier (letters, digits . _ : - /, up to 128): never free text or personal data`,
    );
  }
}

/** La ranura: dónde vive una intención. Dos formularios distintos usan operaciones u objetivos distintos. */
export function slotOf(spec: IntentSpec): string {
  assertSafe("operation", spec.operation);
  assertSafe("target", spec.target);
  return `${spec.operation}|${spec.target}`;
}

export function intentFingerprint(spec: IntentSpec): string {
  return `${slotOf(spec)}|${canonicalize(spec.params)}`;
}

// --- SHA-256 síncrono (la huella que se guarda en la pestaña) --------------------------------------------------------

const K = Uint32Array.from(
  [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
    0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
    0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
  ],
);

export function sha256Hex(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const padded = new Uint8Array((((bytes.length + 9 + 63) >> 6) << 6));
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor((bytes.length * 8) / 0x100000000));
  view.setUint32(padded.length - 4, (bytes.length * 8) >>> 0);

  const h = Uint32Array.from([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const w = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i += 1) {
      const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h[0] += a;
    h[1] += b;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += hh;
  }
  return Array.from(h, (word) => word.toString(16).padStart(8, "0")).join("");
}

// --- Qué le pasó a una petición ----------------------------------------------------------------------------------

function statusOf(error: unknown): number | null {
  if (error && typeof error === "object" && "status" in error && typeof error.status === "number") return error.status;
  return null;
}

/** El `code` que el backend pone en los errores de idempotencia (`{"detail": …, "code": …}`), o `null`. */
export function errorCode(error: unknown): string | null {
  const message = error && typeof error === "object" && "message" in error ? error.message : null;
  if (typeof message !== "string") return null;
  try {
    const body: unknown = JSON.parse(message);
    if (body && typeof body === "object" && "code" in body && typeof body.code === "string") return body.code;
  } catch {
    // el cuerpo no era JSON: no hay código
  }
  return null;
}

/** Cómo trata la clave un fallo. Se decide por el estado HTTP y por el `code`, nunca por el texto de `detail`.
 *
 * Un error **sin** estado HTTP (red caída, timeout, petición abortada) es `retryable`: no se sabe si la petición llegó.
 * Lo que no se reconoce también: ante la duda se conserva la clave, porque cambiarla es lo que duplica un efecto. */
export function classifyFailure(error: unknown): FailureKind {
  const status = statusOf(error);
  if (status === null) return "retryable";
  const code = errorCode(error);
  if (code === "idempotency_outcome_unknown") return "unknown";
  if (code === "idempotency_in_progress") return "retryable";
  if (code === "idempotency_conflict") return "conflict";
  if (status >= 500 || status === 408 || status === 425 || status === 429) return "retryable";
  return "rejected";
}

/** Una respuesta 2xx cuyo cuerpo dice `UNKNOWN_OUTCOME` (p. ej. un fulfillment cuya compra pudo salir): el backend la
 * entrega como éxito HTTP, pero la intención **no** ha terminado. */
export function domainVerdict(result: unknown): Verdict {
  if (result && typeof result === "object" && "status" in result && result.status === "UNKNOWN_OUTCOME") {
    return "unknown";
  }
  return "done";
}

// --- El conservador de claves ----------------------------------------------------------------------------------

interface Entry {
  key: string;
  fingerprint: string;
  phase: IntentPhase;
  inFlight: Promise<unknown> | null;
}

interface StoredIntent {
  fingerprint: string;
  key: string;
  phase: "in_flight" | "retryable" | "unknown";
}

export interface IntentKeeperOptions {
  /** Distingue a un formulario de otro cuando comparten pestaña. */
  scope?: string;
  /** Dónde sobrevive una intención ambigua a una navegación. `null`: solo en memoria. */
  storage?: IntentStorage | null;
  makeKey?: () => string;
}

export interface IntentKeeper {
  /** Ejecuta `send` con la clave de la intención. La misma intención en vuelo devuelve **la misma promesa**. */
  run<T>(spec: IntentSpec, send: (key: string) => Promise<T>, verdict?: (result: T) => Verdict): Promise<T>;
  /** La clave que la intención conserva ahora, o `null`. Para diagnóstico y pruebas; la interfaz no la muestra. */
  keyOf(spec: IntentSpec): string | null;
  phaseOf(spec: IntentSpec): IntentPhase;
  /** La fase de todo el conservador: la más urgente de sus ranuras. */
  phase(): IntentPhase;
  /** Una decisión **deliberada** de que lo anterior ya se comprobó: la próxima acción lleva otra clave. */
  discard(spec?: IntentSpec): void;
  subscribe(listener: () => void): () => void;
}

const URGENCY: IntentPhase[] = ["in_flight", "unknown", "retryable", "rejected", "idle"];

export function createIntentKeeper(options: IntentKeeperOptions = {}): IntentKeeper {
  const makeKey = options.makeKey ?? newIdempotencyKey;
  const storage = options.storage ?? null;
  const scope = options.scope ?? "default";
  const entries = new Map<string, Entry>();
  const listeners = new Set<() => void>();

  const storageKey = (slot: string) => `${STORAGE_PREFIX}:${scope}:${slot}`;

  function notify(): void {
    for (const listener of listeners) listener();
  }

  function persist(slot: string, entry: Entry): void {
    if (!storage) return;
    if (entry.phase === "idle" || entry.phase === "rejected") {
      // Un rechazo definitivo no dejó efecto: el registro «en vuelo» que se escribió al enviar ya no tiene sentido.
      try {
        storage.removeItem(storageKey(slot));
      } catch {
        // nada que borrar
      }
      return;
    }
    const record: StoredIntent = { fingerprint: sha256Hex(entry.fingerprint), key: entry.key, phase: entry.phase };
    try {
      storage.setItem(storageKey(slot), JSON.stringify(record));
    } catch {
      // sin almacenamiento (modo privado, cuota): la clave sigue viva en memoria
    }
  }

  function forget(slot: string): void {
    entries.delete(slot);
    try {
      storage?.removeItem(storageKey(slot));
    } catch {
      // nada que borrar
    }
  }

  function recover(slot: string, fingerprint: string): Entry | null {
    if (!storage) return null;
    let raw: string | null = null;
    try {
      raw = storage.getItem(storageKey(slot));
    } catch {
      return null;
    }
    if (raw === null) return null;
    try {
      const stored = JSON.parse(raw) as StoredIntent;
      const sameIntent = stored.fingerprint === sha256Hex(fingerprint);
      if (sameIntent && typeof stored.key === "string" && SAFE_TOKEN.test(stored.key)) {
        return { key: stored.key, fingerprint, phase: stored.phase === "unknown" ? "unknown" : "retryable", inFlight: null };
      }
    } catch {
      // un registro ilegible se trata como si no existiera
    }
    try {
      storage.removeItem(storageKey(slot)); // otra intención en esa ranura, o basura: no se reutiliza
    } catch {
      // nada que borrar
    }
    return null;
  }

  function settle(slot: string, entry: Entry, phase: IntentPhase): void {
    if (entries.get(slot) !== entry) return; // la ranura ya pasó a otra intención: este resultado no es suyo
    entry.phase = phase;
    entry.inFlight = null;
    persist(slot, entry);
  }

  function run<T>(spec: IntentSpec, send: (key: string) => Promise<T>, verdict: (result: T) => Verdict = domainVerdict) {
    const slot = slotOf(spec);
    const fingerprint = intentFingerprint(spec);
    let entry = entries.get(slot);

    if (entry && entry.fingerprint === fingerprint && entry.inFlight) {
      return entry.inFlight as Promise<T>; // el mismo clic otra vez: no sale una segunda petición
    }
    if (!entry || entry.fingerprint !== fingerprint) {
      // Cambió la intención (o no había ninguna): clave nueva, salvo que la pestaña recuerde esta misma.
      entry = recover(slot, fingerprint) ?? { key: makeKey(), fingerprint, phase: "idle", inFlight: null };
      entries.set(slot, entry);
    }
    const current = entry;
    current.phase = "in_flight";
    persist(slot, current);

    const attempt = (async (): Promise<T> => {
      try {
        const result = await send(current.key);
        if (verdict(result) === "done") {
          if (entries.get(slot) === current) forget(slot); // éxito: la intención se acaba, la próxima será otra
        } else {
          settle(slot, current, "unknown");
        }
        return result;
      } catch (error) {
        const kind = classifyFailure(error);
        if (kind === "conflict") {
          if (entries.get(slot) === current) forget(slot); // la clave quedó atada a otro contenido: no sirve
        } else {
          settle(slot, current, kind === "rejected" ? "rejected" : kind);
        }
        throw error;
      } finally {
        notify();
      }
    })();
    current.inFlight = attempt;
    notify();
    return attempt;
  }

  return {
    run,
    keyOf: (spec) => entries.get(slotOf(spec))?.key ?? null,
    phaseOf: (spec) => entries.get(slotOf(spec))?.phase ?? "idle",
    phase: () => {
      const phases = new Set(Array.from(entries.values(), (entry) => entry.phase));
      return URGENCY.find((phase) => phases.has(phase)) ?? "idle";
    },
    discard: (spec) => {
      if (spec) forget(slotOf(spec));
      else for (const slot of Array.from(entries.keys())) forget(slot);
      notify();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
