import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { test } from "node:test";
import {
  canonicalize,
  classifyFailure,
  createIntentKeeper,
  domainVerdict,
  errorCode,
  intentFingerprint,
  sha256Hex,
  slotOf,
  type IntentSpec,
  type IntentStorage,
} from "./intent-key.ts";

// --- Apoyo -------------------------------------------------------------------------------------------------------

/** Un error como el que lanza `lib/api.ts` (`ApiError`): estado HTTP y el cuerpo de la respuesta como mensaje. */
function apiError(status: number, body: unknown = { detail: "x" }): Error & { status: number } {
  return Object.assign(new Error(typeof body === "string" ? body : JSON.stringify(body)), { status });
}
const IN_PROGRESS = () => apiError(409, { detail: "still being processed", code: "idempotency_in_progress" });
const OUTCOME_UNKNOWN = () => apiError(409, { detail: "does not say", code: "idempotency_outcome_unknown" });
const KEY_CONFLICT = () => apiError(409, { detail: "other content", code: "idempotency_conflict" });
const BUSINESS_409 = () => apiError(409, { detail: "fulfillment is READY: needs PURCHASED" });

function counter(prefix = "k") {
  let n = 0;
  const calls: number[] = [];
  return {
    make: () => {
      n += 1;
      calls.push(n);
      return `${prefix}-${n}`;
    },
    made: () => calls.length,
  };
}

function memoryStorage(): IntentStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

/** Un `send` que anota la clave con la que sale y responde lo que diga el guion (un valor o un error). */
function sender<T>(...script: Array<T | Error | (() => Error)>) {
  const keys: string[] = [];
  const send = async (key: string): Promise<T> => {
    keys.push(key);
    const next = script.length > 1 ? script.shift()! : script[0];
    const outcome = typeof next === "function" ? (next as () => Error)() : next;
    if (outcome instanceof Error) throw outcome;
    return outcome as T;
  };
  return { send, keys };
}

async function failing(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("it should have failed");
}

const PURCHASE: IntentSpec = { operation: "fulfillment.purchase", target: "ful-1", params: { fulfillment_id: "ful-1" } };

// --- A. Doble clic: veinte acciones idénticas a la vez ----------------------------------------------------------

test("A. veinte clics idénticos a la vez son una sola petición con una sola clave", async () => {
  const ids = counter();
  const keeper = createIntentKeeper({ makeKey: ids.make });
  let sent = 0;
  const keys: string[] = [];
  const send = async (key: string) => {
    sent += 1;
    keys.push(key);
    await new Promise((resolve) => setTimeout(resolve, 5));
    return { id: "ful-1", status: "PURCHASED" };
  };

  const clicks = Array.from({ length: 20 }, () => keeper.run(PURCHASE, send));
  const results = await Promise.all(clicks);

  assert.equal(sent, 1, "the other nineteen clicks joined the request in flight");
  assert.deepEqual(keys, ["k-1"]);
  assert.equal(ids.made(), 1);
  assert.ok(results.every((result) => result === results[0]));
  assert.ok(clicks.every((click) => click === clicks[0]), "they all get the same promise");
});

test("A. aunque cada clic aporte su propio `send`, todos salen con la misma clave si el primero sigue en vuelo", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const keys: string[] = [];
  const slow = async (key: string) => {
    keys.push(key);
    await new Promise((resolve) => setTimeout(resolve, 5));
    return "ok";
  };

  await Promise.all(Array.from({ length: 20 }, () => keeper.run(PURCHASE, (key) => slow(key))));

  assert.deepEqual(keys, ["k-1"]);
});

// --- B-E. Lo que conserva la clave -------------------------------------------------------------------------------

test("B. un timeout conserva la clave: el reintento sale con la misma", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const timeout = new DOMException("The operation timed out", "TimeoutError");
  const { send, keys } = sender<string>(timeout as unknown as Error, "ok");

  assert.equal(await failing(keeper.run(PURCHASE, send)), timeout);
  assert.equal(keeper.phaseOf(PURCHASE), "retryable");
  assert.equal(await keeper.run(PURCHASE, send), "ok");

  assert.deepEqual(keys, ["k-1", "k-1"]);
});

test("B. una petición abortada por el navegador también", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(new DOMException("aborted", "AbortError") as unknown as Error, "ok");

  await failing(keeper.run(PURCHASE, send));
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-1"]);
});

test("C. un 5xx transitorio conserva la clave mientras la intención siga vigente", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(() => apiError(503), () => apiError(502), () => apiError(500), "ok");

  for (let attempt = 0; attempt < 3; attempt += 1) {
    assert.equal(keeper.phaseOf(PURCHASE), attempt === 0 ? "idle" : "retryable");
    await failing(keeper.run(PURCHASE, send));
  }
  assert.equal(await keeper.run(PURCHASE, send), "ok");

  assert.deepEqual(keys, ["k-1", "k-1", "k-1", "k-1"]);
});

test("C. 408, 425 y 429 se reintentan con la misma clave", async () => {
  for (const status of [408, 425, 429]) {
    const keeper = createIntentKeeper({ makeKey: counter().make });
    const { send, keys } = sender<string>(() => apiError(status), "ok");
    await failing(keeper.run(PURCHASE, send));
    await keeper.run(PURCHASE, send);
    assert.deepEqual(keys, ["k-1", "k-1"], `status ${status}`);
  }
});

test("D. un fallo de red conserva la clave", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(new TypeError("fetch failed"), new TypeError("fetch failed"), "ok");

  await failing(keeper.run(PURCHASE, send));
  await failing(keeper.run(PURCHASE, send));
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-1", "k-1"]);
});

test("D. un error que no se reconoce también conserva la clave: cambiarla es lo que duplica un efecto", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(new Error("something nobody planned for"), "ok");

  await failing(keeper.run(PURCHASE, send));
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-1"]);
});

test("E. un 409 «en curso» conserva la clave: se espera, no se cambia", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(IN_PROGRESS, IN_PROGRESS, "ok");

  await failing(keeper.run(PURCHASE, send));
  assert.equal(keeper.phaseOf(PURCHASE), "retryable");
  await failing(keeper.run(PURCHASE, send));
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-1", "k-1"]);
});

test("E. un resultado desconocido del backend conserva la clave y no se da por terminado", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(OUTCOME_UNKNOWN);

  await failing(keeper.run(PURCHASE, send));
  assert.equal(keeper.phaseOf(PURCHASE), "unknown");
  await failing(keeper.run(PURCHASE, send));

  assert.deepEqual(keys, ["k-1", "k-1"]);
  assert.equal(keeper.keyOf(PURCHASE), "k-1", "nothing replaced the key behind the person's back");
});

test("E. un 200 con UNKNOWN_OUTCOME (la compra pudo salir) no cierra la intención: la repetición lleva la misma clave", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<{ status: string }>({ status: "UNKNOWN_OUTCOME" }, { status: "PURCHASED" });

  const first = await keeper.run(PURCHASE, send);
  assert.equal(first.status, "UNKNOWN_OUTCOME");
  assert.equal(keeper.phaseOf(PURCHASE), "unknown");
  const second = await keeper.run(PURCHASE, send);
  assert.equal(second.status, "PURCHASED");

  assert.deepEqual(keys, ["k-1", "k-1"]);
  assert.equal(keeper.phaseOf(PURCHASE), "idle", "now it did finish");
  assert.equal(keeper.keyOf(PURCHASE), null);
});

test("E. un rechazo de negocio (409 sin código de idempotencia, 422, 404) conserva la clave: el backend la libera", async () => {
  for (const error of [BUSINESS_409, () => apiError(422), () => apiError(404), () => apiError(400)]) {
    const keeper = createIntentKeeper({ makeKey: counter().make });
    const { send, keys } = sender<string>(error, "ok");
    await failing(keeper.run(PURCHASE, send));
    assert.equal(keeper.phaseOf(PURCHASE), "rejected");
    await keeper.run(PURCHASE, send);
    assert.deepEqual(keys, ["k-1", "k-1"]);
  }
});

test("E. una clave que el backend dice atada a otro contenido se descarta", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(KEY_CONFLICT, "ok");

  await failing(keeper.run(PURCHASE, send));
  assert.equal(keeper.keyOf(PURCHASE), null);
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-2"]);
});

// --- F-I. Lo que cambia la clave ---------------------------------------------------------------------------------

test("F. unos parámetros que cambian de verdad dan una clave nueva", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const refund = (amount: string): IntentSpec => ({
    operation: "order.refund",
    target: "ord-1",
    params: { payment_id: "pay-1", amount: { amount, currency: "EUR" }, reason: "customer_request" },
  });
  const { send, keys } = sender<string>(() => apiError(503));

  await failing(keeper.run(refund("10.00"), send));
  await failing(keeper.run(refund("10.00"), send));
  await failing(keeper.run(refund("12.00"), send));

  assert.deepEqual(keys, ["k-1", "k-1", "k-2"]);
});

test("F. el orden de los campos o un campo `undefined` no cambian la intención; un `null` sí", () => {
  const same = (a: unknown, b: unknown) =>
    intentFingerprint({ operation: "o", target: "t", params: a }) === intentFingerprint({ operation: "o", target: "t", params: b });

  assert.ok(same({ a: 1, b: { c: 2, d: [1, 2] } }, { b: { d: [1, 2], c: 2 }, a: 1 }));
  assert.ok(same({ a: 1, b: undefined }, { a: 1 }));
  assert.ok(!same({ a: 1, b: null }, { a: 1 }));
  assert.ok(!same({ list: [1, 2] }, { list: [2, 1] }), "the order of a list is part of the intent");
  assert.ok(!same({ n: "1" }, { n: 1 }), "a string is not a number");
  assert.equal(canonicalize({ b: 2, a: 1 }), '{"a":1,"b":2}');
  assert.equal(canonicalize(undefined), "null");
  assert.equal(canonicalize(new Date("2026-10-02T10:00:00Z")), '"2026-10-02T10:00:00.000Z"');
});

test("G. otra operación sobre el mismo recurso es otra intención con otra clave, y cada una conserva la suya", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const ship: IntentSpec = { operation: "fulfillment.ship", target: "ful-1", params: { fulfillment_id: "ful-1" } };
  const failBoth = sender<string>(() => apiError(503));

  await failing(keeper.run(PURCHASE, failBoth.send));
  await failing(keeper.run(ship, failBoth.send));
  await failing(keeper.run(PURCHASE, failBoth.send));

  assert.deepEqual(failBoth.keys, ["k-1", "k-2", "k-1"]);
});

test("H. otro recurso es otra intención con otra clave", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const other: IntentSpec = { ...PURCHASE, target: "ful-2", params: { fulfillment_id: "ful-2" } };
  const { send, keys } = sender<string>(() => apiError(503));

  await failing(keeper.run(PURCHASE, send));
  await failing(keeper.run(other, send));
  await failing(keeper.run(PURCHASE, send));
  await failing(keeper.run(other, send));

  assert.deepEqual(keys, ["k-1", "k-2", "k-1", "k-2"]);
});

test("I. tras un éxito, la siguiente acción deliberada lleva otra clave y la intención anterior no se reutiliza", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<{ status: string }>({ status: "PURCHASED" });

  await keeper.run(PURCHASE, send);
  assert.equal(keeper.keyOf(PURCHASE), null);
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-2"]);
});

test("I. `discard` es la decisión de una persona de empezar otra intención: la siguiente clave es nueva", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const { send, keys } = sender<string>(OUTCOME_UNKNOWN, "ok");

  await failing(keeper.run(PURCHASE, send));
  keeper.discard(PURCHASE);
  await keeper.run(PURCHASE, send);

  assert.deepEqual(keys, ["k-1", "k-2"]);
});

test("I. un resultado tardío de una intención que ya no es la vigente no toca a la nueva", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  let release: (value: string) => void = () => {};
  const old = keeper.run(PURCHASE, () => new Promise<string>((resolve) => (release = resolve)));
  keeper.discard(PURCHASE);
  const fresh = sender<string>(() => apiError(503));
  await failing(keeper.run(PURCHASE, fresh.send));

  release("late");
  await old;

  assert.equal(keeper.phaseOf(PURCHASE), "retryable", "the late success of the discarded intent did not close the new one");
  assert.equal(keeper.keyOf(PURCHASE), "k-2");
});

// --- J. Formularios independientes -------------------------------------------------------------------------------

test("J. dos conservadores no comparten intención aunque pidan lo mismo", async () => {
  const one = createIntentKeeper({ scope: "form-a", makeKey: counter("a").make });
  const two = createIntentKeeper({ scope: "form-b", makeKey: counter("b").make });
  const { send, keys } = sender<string>(() => apiError(503));

  await failing(one.run(PURCHASE, send));
  await failing(two.run(PURCHASE, send));

  assert.deepEqual(keys, ["a-1", "b-1"]);
});

test("J. dos conservadores con el mismo almacén pero otro ámbito no se recuperan la intención", async () => {
  const storage = memoryStorage();
  const one = createIntentKeeper({ scope: "form-a", storage, makeKey: counter("a").make });
  const two = createIntentKeeper({ scope: "form-b", storage, makeKey: counter("b").make });
  const { send, keys } = sender<string>(() => apiError(503));

  await failing(one.run(PURCHASE, send));
  await failing(two.run(PURCHASE, send));

  assert.deepEqual(keys, ["a-1", "b-1"]);
});

// --- K. Rerender -------------------------------------------------------------------------------------------------

test("K. leer el estado (lo que hace un render) no genera ni cambia ninguna clave", async () => {
  const ids = counter();
  const keeper = createIntentKeeper({ makeKey: ids.make });
  const { send } = sender<string>(() => apiError(503));
  assert.equal(ids.made(), 0, "creating the keeper generates nothing");
  await failing(keeper.run(PURCHASE, send));

  for (let render = 0; render < 50; render += 1) {
    keeper.phase();
    keeper.phaseOf(PURCHASE);
    keeper.keyOf(PURCHASE);
  }

  assert.equal(ids.made(), 1);
  assert.equal(keeper.keyOf(PURCHASE), "k-1");
});

test("K. el gancho de React crea el conservador una sola vez por componente y nunca genera claves al renderizar", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("./use-intent.ts", import.meta.url), "utf8");

  assert.match(source, /useState\(\(\) => createIntentKeeper\(/, "the keeper is created in a lazy state initialiser");
  assert.match(source, /useSyncExternalStore\(/);
  assert.doesNotMatch(source, /randomUUID|newIdempotencyKey|makeKey/, "a key is made only inside the keeper's `run`");
  assert.doesNotMatch(source, /useRef|useEffect/, "no effect or ref decides a key");
});

// --- L. Navegación -----------------------------------------------------------------------------------------------

test("L. una intención ambigua sobrevive a una navegación: el mismo formulario recupera la misma clave", async () => {
  const storage = memoryStorage();
  const before = createIntentKeeper({ scope: "operations", storage, makeKey: counter("a").make });
  const lost = sender<string>(new DOMException("timed out", "TimeoutError") as unknown as Error);
  await failing(before.run(PURCHASE, lost.send));

  const after = createIntentKeeper({ scope: "operations", storage, makeKey: counter("b").make });
  const retry = sender<string>("ok");
  await after.run(PURCHASE, retry.send);

  assert.deepEqual(retry.keys, ["a-1"], "the same intent after a navigation is the same key");
  assert.equal(storage.data.size, 0, "and the success cleaned the tab");
});

test("L. un resultado desconocido también se recupera tras navegar", async () => {
  const storage = memoryStorage();
  const before = createIntentKeeper({ scope: "operations", storage, makeKey: counter("a").make });
  await before.run(PURCHASE, sender<{ status: string }>({ status: "UNKNOWN_OUTCOME" }).send);

  const after = createIntentKeeper({ scope: "operations", storage, makeKey: counter("b").make });

  assert.equal(after.phaseOf(PURCHASE), "idle");
  const retry = sender<{ status: string }>({ status: "PURCHASED" });
  await after.run(PURCHASE, retry.send);
  assert.deepEqual(retry.keys, ["a-1"]);
});

test("L. tras navegar, unos parámetros distintos no recuperan la clave y el registro viejo se sustituye", async () => {
  const storage = memoryStorage();
  const before = createIntentKeeper({ scope: "operations", storage, makeKey: counter("a").make });
  await failing(before.run(PURCHASE, sender<string>(() => apiError(503)).send));

  const after = createIntentKeeper({ scope: "operations", storage, makeKey: counter("b").make });
  const changed: IntentSpec = { ...PURCHASE, params: { fulfillment_id: "ful-1", note: "another intent" } };
  const retry = sender<string>(() => apiError(503));
  await failing(after.run(changed, retry.send));

  assert.deepEqual(retry.keys, ["b-1"]);
  const stored = JSON.parse([...storage.data.values()][0]);
  assert.equal(stored.key, "b-1", "the record now belongs to the new intent");
});

test("L. un rechazo definitivo no se guarda: no hubo efecto y no hay nada que recuperar", async () => {
  const storage = memoryStorage();
  const keeper = createIntentKeeper({ scope: "operations", storage, makeKey: counter().make });

  await failing(keeper.run(PURCHASE, sender<string>(() => apiError(422)).send));

  assert.equal(storage.data.size, 0);
});

test("L. un éxito, un descarte o un conflicto de clave borran lo guardado", async () => {
  const storage = memoryStorage();
  const keeper = createIntentKeeper({ scope: "operations", storage, makeKey: counter().make });
  await failing(keeper.run(PURCHASE, sender<string>(() => apiError(503)).send));
  assert.equal(storage.data.size, 1);

  await keeper.run(PURCHASE, sender<string>("ok").send);
  assert.equal(storage.data.size, 0, "success");

  await failing(keeper.run(PURCHASE, sender<string>(() => apiError(503)).send));
  keeper.discard(PURCHASE);
  assert.equal(storage.data.size, 0, "discard");

  await failing(keeper.run(PURCHASE, sender<string>(KEY_CONFLICT).send));
  assert.equal(storage.data.size, 0, "key conflict");
});

test("L. un almacén que falla o un registro ilegible no rompe nada: se sigue en memoria", async () => {
  const broken: IntentStorage = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("quota");
    },
    removeItem: () => {
      throw new Error("blocked");
    },
  };
  const keeper = createIntentKeeper({ storage: broken, makeKey: counter().make });
  const { send, keys } = sender<string>(() => apiError(503), "ok");
  await failing(keeper.run(PURCHASE, send));
  await keeper.run(PURCHASE, send);
  assert.deepEqual(keys, ["k-1", "k-1"]);

  const storage = memoryStorage();
  storage.data.set("amazona.intent.v1:default:fulfillment.purchase|ful-1", "{not json");
  const other = createIntentKeeper({ storage, makeKey: counter("z").make });
  const retry = sender<string>("ok");
  await other.run(PURCHASE, retry.send);
  assert.deepEqual(retry.keys, ["z-1"]);
});

test("L. no hay caducidad por tiempo: «hace mucho» no es «no ocurrió»", async () => {
  const storage = memoryStorage();
  const before = createIntentKeeper({ scope: "operations", storage, makeKey: counter("a").make });
  await failing(before.run(PURCHASE, sender<string>(new TypeError("fetch failed")).send));
  const record = JSON.parse([...storage.data.values()][0]);

  assert.deepEqual(Object.keys(record).sort(), ["fingerprint", "key", "phase"], "no timestamp decides anything");
});

// --- M. Seguridad ------------------------------------------------------------------------------------------------

test("M. la clave es opaca: ni la operación, ni el objetivo, ni los parámetros, ni nada personal viajan en ella", async () => {
  const personal = {
    email: "ana.garcia@example.com",
    name: "Ana García",
    phone: "+34 600 000 000",
    address: "Calle Mayor 1",
    token: "Bearer eyJhbGciOi.secret.token",
    secret: "fakekey_0123456789",
  };
  const spec: IntentSpec = { operation: "order.create", target: "ord-9f3a", params: personal };
  const storage = memoryStorage();
  const keeper = createIntentKeeper({ scope: "checkout", storage });
  const { send, keys } = sender<string>(() => apiError(503));

  await failing(keeper.run(spec, send));

  const [key] = keys;
  assert.match(key, /^[A-Za-z0-9._:-]{1,128}$/, "what the backend accepts");
  for (const fragment of ["ana", "garcia", "example", "600", "calle", "bearer", "secret", "fakekey", "order", "ord-9f3a"]) {
    assert.ok(!key.toLowerCase().includes(fragment), `the key leaks ${fragment}`);
  }
  const written = [...storage.data.entries()].flat().join(" ").toLowerCase();
  for (const fragment of ["ana", "garcia", "example.com", "600 000", "calle mayor", "bearer", "fakekey"]) {
    assert.ok(!written.includes(fragment), `the tab storage keeps ${fragment}: only a hash of the parameters may stay`);
  }
});

test("M. las claves generadas por defecto son únicas, opacas y aceptadas por el backend", async () => {
  const keeper = createIntentKeeper();
  const seen = new Set<string>();
  for (let i = 0; i < 40; i += 1) {
    const spec: IntentSpec = { operation: "order.create", target: `ord-${i}`, params: { n: i } };
    await keeper.run(spec, async (key) => {
      seen.add(key);
      return "ok";
    });
  }
  assert.equal(seen.size, 40);
  for (const key of seen) assert.match(key, /^[A-Za-z0-9._:-]{1,128}$/);
});

test("M. el objetivo y la operación son identificadores opacos: un correo o un nombre se rechazan", () => {
  assert.throws(() => slotOf({ operation: "order.create", target: "ana.garcia@example.com" }), TypeError);
  assert.throws(() => slotOf({ operation: "order.create", target: "Ana García" }), TypeError);
  assert.throws(() => slotOf({ operation: "create order", target: "ord-1" }), TypeError);
  assert.throws(() => slotOf({ operation: "o", target: "" }), TypeError);
  assert.equal(slotOf({ operation: "fulfillment.purchase", target: "3f2a9c1e-77b0-4c1d-8a55-0d6c2f1e9b21" }).length > 0, true);
});

// --- Clasificación y apoyo ---------------------------------------------------------------------------------------

test("el error se clasifica por estado y código, nunca por el texto de `detail`", () => {
  const misleading = apiError(409, { detail: "idempotency_outcome_unknown in progress still being processed" });
  assert.equal(classifyFailure(misleading), "rejected", "words in the detail decide nothing");
  assert.equal(classifyFailure(IN_PROGRESS()), "retryable");
  assert.equal(classifyFailure(OUTCOME_UNKNOWN()), "unknown");
  assert.equal(classifyFailure(KEY_CONFLICT()), "conflict");
  assert.equal(classifyFailure(apiError(500, "<html>boom</html>")), "retryable", "a body that is not JSON is fine");
  assert.equal(classifyFailure(apiError(428)), "rejected");
  assert.equal(classifyFailure(new TypeError("fetch failed")), "retryable");
  assert.equal(classifyFailure("a string"), "retryable");
  assert.equal(classifyFailure(null), "retryable");
  assert.equal(errorCode(IN_PROGRESS()), "idempotency_in_progress");
  assert.equal(errorCode(new Error("plain")), null);
});

test("un 2xx con UNKNOWN_OUTCOME no es un éxito; cualquier otro resultado, sí", () => {
  assert.equal(domainVerdict({ status: "UNKNOWN_OUTCOME", unknown_phase: "purchase" }), "unknown");
  assert.equal(domainVerdict({ status: "PURCHASED" }), "done");
  assert.equal(domainVerdict({ status: "SENDING" }), "done", "a refund SENDING is a legitimate answer");
  assert.equal(domainVerdict(undefined), "done");
  assert.equal(domainVerdict(null), "done");
});

test("el conservador avisa a quien escucha y la fase agregada es la más urgente", async () => {
  const keeper = createIntentKeeper({ makeKey: counter().make });
  const seen: string[] = [];
  const stop = keeper.subscribe(() => seen.push(keeper.phase()));
  const other: IntentSpec = { operation: "fulfillment.ship", target: "ful-1", params: {} };

  await failing(keeper.run(PURCHASE, sender<string>(() => apiError(503)).send));
  await failing(keeper.run(other, sender<string>(OUTCOME_UNKNOWN).send));
  assert.equal(keeper.phase(), "unknown", "unknown outranks retryable");
  keeper.discard();
  assert.equal(keeper.phase(), "idle");
  stop();
  const count = seen.length;
  await keeper.run(PURCHASE, sender<string>("ok").send);

  assert.ok(seen.includes("in_flight") && seen.includes("retryable"));
  assert.equal(seen.length, count, "after unsubscribing nobody is told");
});

test("SHA-256: los vectores conocidos y el mismo resultado que node:crypto", () => {
  assert.equal(sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  assert.equal(
    sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
  );
  for (let length = 0; length <= 130; length += 1) {
    const text = randomBytes(length).toString("latin1") + "ñ€😀";
    assert.equal(sha256Hex(text), createHash("sha256").update(text, "utf8").digest("hex"), `length ${length}`);
  }
});
