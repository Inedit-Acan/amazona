import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDecimal, toText } from "./decimal.ts";
import {
  ORIGINS,
  ORIGIN_LABEL,
  ORIGIN_MEANING,
  ORIGIN_MULTIPLE_LABEL,
  ORIGIN_NONE_LABEL,
  ORIGIN_UNKNOWN_LABEL,
  MixedOriginError,
  PROVENANCE_LABEL,
  add,
  addVerified,
  declared,
  demo,
  isOrigin,
  originLabel,
  originMeaning,
  originName,
  planned,
  subtract,
  subtractVerified,
  summarizeOrigins,
  total,
  verified,
} from "./provenance.ts";

// La procedencia va en el tipo (M45, Commit 10): sumar un hecho con una proyección no compila. Y desde M46 (Commit 4,
// ADR 0031 §11) un hecho verificado lleva además su ORIGEN en el tipo: sumar dos orígenes distintos tampoco compila.
//
// Lo que un test de ejecución puede comprobar es lo que queda en tiempo de ejecución: que la procedencia y el origen
// viajan con la cifra y que una operación nunca los cambia por sorpresa. Que MEZCLAR no compile lo comprueba `tsc` (con
// los `@ts-expect-error` de abajo, que fallarían si el tipo dejara de impedirlo).

const d = (text: string) => parseDecimal(text)!;

test("cada cifra lleva su procedencia, y las cuatro existen", () => {
  assert.equal(verified(d("1.0000"), "mock").provenance, "verified");
  assert.equal(declared(d("1.0000")).provenance, "declared");
  assert.equal(planned(d("1.0000")).provenance, "planned");
  assert.equal(demo(d("1.0000")).provenance, "demo");
  assert.deepEqual(Object.keys(PROVENANCE_LABEL).sort(), ["declared", "demo", "planned", "verified"]);
});

test("sumar dos cifras de la misma procedencia conserva la procedencia y el importe exacto", () => {
  const sum = addVerified(verified(d("10.5000"), "mock"), verified(d("0.5000"), "mock"));
  assert.equal(sum.provenance, "verified");
  assert.equal(sum.origin, "mock");
  assert.equal(toText(sum.value), "11.0000");
  const difference = subtract(declared(d("10.0000")), declared(d("2.5000")));
  assert.equal(difference.provenance, "declared");
  assert.equal(toText(difference.value), "7.5000");
  const net = subtractVerified(verified(d("10.0000"), "real"), verified(d("2.5000"), "real"));
  assert.equal(net.origin, "real");
  assert.equal(toText(net.value), "7.5000");
});

test("una lista vacía no es cero: es «sin datos»", () => {
  assert.equal(total([]), null);
  const one = total([planned(d("3.0000"))]);
  assert.equal(one?.provenance, "planned");
  assert.equal(toText(one!.value), "3.0000");
});

test("el total de una lista homogénea es exacto", () => {
  const sum = total([planned(d("0.1000")), planned(d("0.2000")), planned(d("0.3000"))]);
  assert.equal(toText(sum!.value), "0.6000");
});

test("la etiqueta de cada procedencia dice lo que promete, y ninguna dice «real»", () => {
  assert.equal(PROVENANCE_LABEL.verified, "Registro verificado");
  assert.equal(PROVENANCE_LABEL.declared, "Declarado");
  assert.equal(PROVENANCE_LABEL.planned, "Proyección (PLAN)");
  assert.equal(PROVENANCE_LABEL.demo, "Demostración");
  for (const label of Object.values(PROVENANCE_LABEL)) {
    assert.ok(!/\breal(es)?\b/i.test(label), `«${label}» afirma más de lo que el backend demuestra`);
  }
});

// --- Mezclar orígenes ----------------------------------------------------------------------------------------------

test("sumar hechos de orígenes distintos lanza: nunca devuelve una cifra que cruce orígenes", () => {
  // Con orígenes que vienen de datos (no literales) el tipo es `Origin` y solo el tiempo de ejecución puede impedirlo.
  const fromData = (origin: string) => verified(d("1.0000"), origin as (typeof ORIGINS)[number]);
  assert.throws(() => addVerified(fromData("mock"), fromData("real")), MixedOriginError);
  assert.throws(() => addVerified(fromData("sandbox"), fromData("real")), MixedOriginError);
  assert.throws(() => subtractVerified(fromData("mock"), fromData("sandbox")), /orígenes distintos \(mock y sandbox\)/);
});

test("con orígenes conocidos en el tipo, mezclar NO compila", () => {
  const mock = verified(d("1.0000"), "mock");
  const real = verified(d("1.0000"), "real");
  assert.throws(() => {
    // @ts-expect-error mock y real son magnitudes distintas: el tipo lo impide
    addVerified(mock, real);
  }, MixedOriginError);
  // Solo comprobación de tipos: esta función no se ejecuta (en ejecución `add` no distingue orígenes; por eso el tipo
  // no la admite para hechos verificados y hay que usar `addVerified`).
  const compileOnly = () => {
    // @ts-expect-error la suma genérica ya no admite hechos verificados (llevan origen): hay que usar addVerified
    return add(mock, mock);
  };
  assert.equal(typeof compileOnly, "function");
});

// --- El vocabulario de origen ---------------------------------------------------------------------------------------

test("el vocabulario de orígenes es cerrado y es el del backend", () => {
  assert.deepEqual([...ORIGINS], ["mock", "sandbox", "real"]);
  for (const origin of ORIGINS) assert.equal(isOrigin(origin), true);
  for (const strange of ["composite", "REAL", "Mock", "", null, undefined, 3, {}]) assert.equal(isOrigin(strange), false);
});

test("cada origen tiene una etiqueta y un significado propios, sin mezclarse", () => {
  assert.deepEqual(ORIGIN_LABEL, { mock: "Simulado", sandbox: "Entorno de pruebas", real: "Proveedor real" });
  assert.equal(new Set(Object.values(ORIGIN_LABEL)).size, 3, "tres orígenes, tres etiquetas distintas");
  assert.equal(new Set(Object.values(ORIGIN_MEANING)).size, 3);
  assert.ok(ORIGIN_MEANING.real.includes("no confirma"), "«proveedor real» no afirma que el dinero esté liquidado");
});

test("solo el origen «real» puede decir «real»: ni mock, ni sandbox, ni varios, ni sin datos", () => {
  const claim = /\breal(es)?\b/i;
  assert.ok(claim.test(ORIGIN_LABEL.real));
  for (const text of [
    ORIGIN_LABEL.mock,
    ORIGIN_LABEL.sandbox,
    ORIGIN_MULTIPLE_LABEL,
    ORIGIN_NONE_LABEL,
    ORIGIN_UNKNOWN_LABEL,
    ORIGIN_MEANING.mock,
    ORIGIN_MEANING.sandbox,
  ]) {
    assert.ok(!claim.test(text), `«${text}» dice «real» sin ser el origen real`);
  }
});

test("sin hechos monetarios no hay origen: no se inventa ninguno", () => {
  assert.deepEqual(summarizeOrigins([]), { kind: "none" });
  assert.equal(originLabel(summarizeOrigins([])), "Sin cobro");
});

test("un origen, tres orígenes y varios: cada resumen dice exactamente lo que hay", () => {
  for (const origin of ORIGINS) {
    assert.deepEqual(summarizeOrigins([origin, origin]), { kind: "single", origin });
    assert.equal(originLabel(summarizeOrigins([origin])), ORIGIN_LABEL[origin]);
  }
  assert.deepEqual(summarizeOrigins(["sandbox", "mock"]), { kind: "multiple", origins: ["mock", "sandbox"] });
  assert.deepEqual(summarizeOrigins(["real", "mock", "sandbox"]), { kind: "multiple", origins: ["mock", "real", "sandbox"] });
  assert.equal(originLabel(summarizeOrigins(["mock", "real"])), "Varios orígenes");
});

test("un valor fuera del vocabulario no se traduce a ningún origen: «Sin datos de origen»", () => {
  for (const strange of ["composite", "REAL", "", null, undefined]) {
    const summary = summarizeOrigins([strange]);
    assert.equal(summary.kind, "unknown");
    assert.equal(originLabel(summary), "Sin datos de origen");
    assert.equal(originName(strange), "Sin datos de origen");
  }
  // Y un valor raro junto a uno conocido tampoco se esconde detrás del conocido.
  assert.equal(summarizeOrigins(["mock", "composite"]).kind, "unknown");
  assert.equal(originMeaning(summarizeOrigins(["composite"])).includes("no se interpreta"), true);
});

test("el significado de varios orígenes los nombra a todos y dice que ninguna cifra los suma", () => {
  const meaning = originMeaning(summarizeOrigins(["mock", "sandbox"]));
  assert.ok(meaning.includes("Simulado") && meaning.includes("Entorno de pruebas"));
  assert.match(meaning, /ninguna cifra los suma/);
});
