import assert from "node:assert/strict";
import { test } from "node:test";
import {
  add,
  equals,
  fromInteger,
  isNegative,
  isZero,
  multiplyByCount,
  parseDecimal,
  subtract,
  toText,
  ZERO,
} from "./decimal.ts";

// Aritmética con dinero (M45, Commit 10). Lo único que importa: que nunca pierda un céntimo.

const d = (text: string) => {
  const value = parseDecimal(text);
  assert.notEqual(value, null, `«${text}» debería ser un decimal`);
  return value!;
};

test("el texto del backend va y vuelve sin perder nada", () => {
  for (const text of ["0.0000", "10.0000", "1234.5600", "-12.5000", "0.0001", "999999999999999999.9999"]) {
    assert.equal(toText(d(text)), text);
  }
});

test("un importe de 17 dígitos sobrevive; con `float` no lo haría", () => {
  const text = "12345678901234567.8900";
  assert.equal(toText(d(text)), text);
  // La prueba de que esto no es una precaución teórica:
  assert.notEqual(String(Number("12345678901234567.89")), "12345678901234567.89");
});

test("sumar y restar es exacto incluso con los céntimos que un `float` rompe", () => {
  assert.equal(toText(add(d("0.1000"), d("0.2000"))), "0.3000");
  assert.notEqual(0.1 + 0.2, 0.3); // lo que haría un `float`
  assert.equal(toText(subtract(d("100.0000"), d("0.0001"))), "99.9999");
  assert.equal(toText(add(d("-5.0000"), d("5.0000"))), "0.0000");
});

test("multiplicar por unidades es exacto y sólo acepta enteros", () => {
  assert.equal(toText(multiplyByCount(d("12.3400"), 3)!), "37.0200");
  assert.equal(toText(multiplyByCount(d("0.0001"), 10_000)!), "1.0000");
  assert.equal(toText(multiplyByCount(d("5.0000"), 0)!), "0.0000");
  assert.equal(multiplyByCount(d("1.0000"), 1.5), null, "media unidad no es una cantidad de línea");
  assert.equal(multiplyByCount(d("1.0000"), Number.NaN), null);
});

test("lo que no es un decimal se rechaza: no se adivina", () => {
  for (const bad of ["", "abc", "1,50", "1.2.3", "€10", " ", "1e3", "NaN", "Infinity"]) {
    assert.equal(parseDecimal(bad), null, `«${bad}» no es un importe`);
  }
});

test("más precisión de la que existe se rechaza; los ceros de más no estorban", () => {
  assert.equal(parseDecimal("1.00001"), null, "una cienmilésima no cabe en el registro");
  assert.equal(toText(d("1.00000")), "1.0000");
  assert.equal(toText(d("1.5")), "1.5000");
  assert.equal(toText(d("1.")), "1.0000");
});

test("el cero es un valor, no una ausencia", () => {
  assert.equal(isZero(ZERO), true);
  assert.equal(toText(ZERO), "0.0000");
  assert.equal(isZero(subtract(d("7.0000"), d("7.0000"))), true);
  assert.equal(isNegative(ZERO), false);
  assert.equal(isNegative(d("-0.0001")), true);
  assert.equal(equals(d("2.5000"), d("2.5")), true);
});

test("un entero de unidades se convierte en importe; un decimal no", () => {
  assert.equal(toText(fromInteger(7)!), "7.0000");
  assert.equal(fromInteger(1.5), null);
  assert.equal(fromInteger(Number.MAX_SAFE_INTEGER + 2), null);
});

test("sumar mil veces un céntimo da exactamente diez euros", () => {
  let total = ZERO;
  for (let i = 0; i < 1000; i += 1) total = add(total, d("0.0100"));
  assert.equal(toText(total), "10.0000");
});
