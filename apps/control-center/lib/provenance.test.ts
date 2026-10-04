import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDecimal, toText } from "./decimal.ts";
import { add, declared, demo, planned, PROVENANCE_LABEL, subtract, total, verified } from "./provenance.ts";

// La procedencia va en el tipo (M45, Commit 10): sumar un hecho con una proyección no compila.
//
// Lo que un test de ejecución puede comprobar es lo que queda en tiempo de ejecución: que la procedencia viaja con la
// cifra y que una operación nunca la cambia por sorpresa. Que MEZCLAR no compile lo comprueba `tsc` (y lo fija una
// prueba de frontera que lee este fichero y el de `cfo-margin`).

const d = (text: string) => parseDecimal(text)!;

test("cada cifra lleva su procedencia, y las cuatro existen", () => {
  assert.equal(verified(d("1.0000")).provenance, "verified");
  assert.equal(declared(d("1.0000")).provenance, "declared");
  assert.equal(planned(d("1.0000")).provenance, "planned");
  assert.equal(demo(d("1.0000")).provenance, "demo");
  assert.deepEqual(Object.keys(PROVENANCE_LABEL).sort(), ["declared", "demo", "planned", "verified"]);
});

test("sumar dos cifras de la misma procedencia conserva la procedencia y el importe exacto", () => {
  const sum = add(verified(d("10.5000")), verified(d("0.5000")));
  assert.equal(sum.provenance, "verified");
  assert.equal(toText(sum.value), "11.0000");
  const difference = subtract(declared(d("10.0000")), declared(d("2.5000")));
  assert.equal(difference.provenance, "declared");
  assert.equal(toText(difference.value), "7.5000");
});

test("una lista vacía no es cero: es «sin datos»", () => {
  assert.equal(total([]), null);
  const one = total([planned(d("3.0000"))]);
  assert.equal(one?.provenance, "planned");
  assert.equal(toText(one!.value), "3.0000");
});

test("el total de una lista homogénea es exacto", () => {
  const sum = total([verified(d("0.1000")), verified(d("0.2000")), verified(d("0.3000"))]);
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
