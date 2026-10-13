import assert from "node:assert/strict";
import { test } from "node:test";
import {
  isUsable,
  listOf,
  READ_ERROR_TEXT,
  READ_UNAVAILABLE_TEXT,
  READ_UNAVAILABLE_VALUE,
  READ_UNREAD_TEXT,
  readErrorText,
  readList,
  unreadState,
  worstOf,
  type ReadState,
} from "./read-state.ts";
import { FAILURES, INVALID_PAYLOADS, TECHNICAL } from "./read-test-support.ts";

// Una lectura es UNA de cuatro cosas —loaded, empty, unread, error— y ninguna se confunde con otra (M46, Commit 6).

test("una lista con contenido es `loaded`, y una lista vacía VÁLIDA es `empty`: no son lo mismo", async () => {
  const loaded = await readList(async () => [1, 2], "los agentes");
  const empty = await readList(async () => [] as number[], "los agentes");

  assert.deepEqual(loaded, { kind: "loaded", data: [1, 2] });
  assert.deepEqual(empty, { kind: "empty" });
  assert.notDeepEqual(loaded, empty);
});

for (const [name, failure] of Object.entries(FAILURES)) {
  test(`un fallo («${name}») es \`error\`: ni lista vacía, ni datos, ni texto técnico`, async () => {
    const state = await readList(async () => {
      throw failure();
    }, "los agentes");

    assert.equal(state.kind, "error");
    assert.ok(!("data" in state), "un error no lleva datos, ni vacíos");
    if (state.kind === "error") {
      assert.doesNotMatch(state.message, TECHNICAL, `el mensaje enseña algo técnico: ${state.message}`);
      assert.doesNotMatch(state.message, /Sin datos|No hay|^0\b/, "un fallo no se dice como ausencia de datos");
      assert.ok(state.message.length > 0);
    }
  });
}

for (const [name, payload] of INVALID_PAYLOADS) {
  test(`una respuesta que no es una lista (${name}) es \`error\`, no una lista vacía`, async () => {
    const state = await readList(async () => payload as unknown[], "las aprobaciones");

    assert.equal(state.kind, "error");
    if (state.kind === "error") assert.doesNotMatch(state.message, TECHNICAL);
  });
}

test("una lectura síncrona que lanza también es un error", async () => {
  const state = await readList(() => {
    throw new Error("boom");
  }, "los agentes");

  assert.equal(state.kind, "error");
});

test("el mensaje nombra qué no se pudo leer y distingue sesión y permiso, sin estados ni detalles", () => {
  assert.equal(readErrorText(500, "los agentes"), "No se pudieron cargar los agentes.");
  assert.equal(readErrorText(undefined, "las aprobaciones"), "No se pudieron cargar las aprobaciones.");
  // Concordancia con un sujeto en singular.
  assert.equal(readErrorText(503, "el catálogo de productos"), "No se pudo cargar el catálogo de productos.");
  assert.equal(readErrorText(500, "el log de ejecuciones"), "No se pudo cargar el log de ejecuciones.");
  assert.match(readErrorText(401, "los agentes"), /sesión/);
  assert.match(readErrorText(403, "los agentes"), /permiso para ver los agentes/);
  for (const status of [undefined, 400, 404, 422, 500, 502, 503]) {
    assert.doesNotMatch(readErrorText(status, "x"), TECHNICAL);
  }
});

test("recuperación: la misma lectura que falló, al repetirse, vuelve a dar datos (sin arrastrar el error)", async () => {
  let fail = true;
  const read = async () => {
    if (fail) throw FAILURES["500"]();
    return ["a"];
  };

  const first = await readList(read, "los agentes");
  fail = false;
  const second = await readList(read, "los agentes");

  assert.equal(first.kind, "error");
  assert.deepEqual(second, { kind: "loaded", data: ["a"] });
});

test("cada intento es UNA petición: no hay reintentos automáticos escondidos", async () => {
  let calls = 0;
  await readList(async () => {
    calls += 1;
    throw FAILURES["503"]();
  }, "los agentes");

  assert.equal(calls, 1);
});

test("listOf: solo una lectura válida da lista; un error o un «sin leer» no dan `[]`, dan `null`", () => {
  const states: ReadState<number[]>[] = [
    { kind: "loaded", data: [1] },
    { kind: "empty" },
    { kind: "unread", reason: "x" },
    { kind: "error", message: "x" },
  ];

  assert.deepEqual(states.map(listOf), [[1], [], null, null]);
  assert.deepEqual(states.map(isUsable), [true, true, false, false]);
});

test("worstOf: el error pesa más que lo no leído, y si todo es válido no hay peor", () => {
  const ok: ReadState<number[]> = { kind: "loaded", data: [1] };
  const empty: ReadState<number[]> = { kind: "empty" };
  const unread = unreadState("no se leyó");
  const error: ReadState<number[]> = { kind: "error", message: "x" };

  assert.equal(worstOf([ok, empty]), null);
  assert.equal(worstOf([ok, unread]), "unread");
  assert.equal(worstOf([unread, error, ok]), "error");
});

test("los textos para el usuario no son técnicos y los cuatro estados se distinguen", () => {
  for (const text of [READ_ERROR_TEXT, READ_UNAVAILABLE_TEXT, READ_UNREAD_TEXT, READ_UNAVAILABLE_VALUE]) {
    assert.doesNotMatch(text, TECHNICAL);
    assert.doesNotMatch(text, /^0$|Sin datos|No hay/);
  }
  assert.equal(new Set([READ_ERROR_TEXT, READ_UNREAD_TEXT, READ_UNAVAILABLE_VALUE]).size, 3);
});
