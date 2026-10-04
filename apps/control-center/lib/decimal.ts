// Aritmética con dinero, sin `float` (M45, Commit 10).
//
// El backend manda los importes como TEXTO decimal exacto de 4 decimales ("1234.5600") precisamente para que nadie los
// convierta a `number`: con 17 dígitos significativos un `float` ya pierde céntimos. Hasta ahora el Panel solo tenía que
// FORMATEAR ese texto; el CFO además tiene que SUMAR (coste de línea = coste unitario × unidades, y el total del pedido).
//
// Así que aquí vive la única aritmética con dinero de la aplicación, sobre `bigint` escalado a 4 decimales. No hay
// `Number()`, no hay `parseFloat`, no hay `toFixed`: una prueba de frontera lo comprueba leyendo este fichero.

/** Importe exacto: céntimos de diezmilésima. `10.0000 €` es `100000n`. */
export interface Decimal {
  readonly units: bigint;
}

/** Decimales con los que trabaja el backend (`Numeric(18,4)`). */
export const SCALE = 4;
// `BigInt(...)` y no un literal `0n`: el proyecto compila a ES2017, que no admite literales BigInt (sí la función).
const NOUGHT = BigInt(0);
const TEN = BigInt(10);
const FACTOR = TEN ** BigInt(SCALE);

export const ZERO: Decimal = { units: NOUGHT };

const PATTERN = /^(-?)(\d+)(?:\.(\d*))?$/;

/** Texto decimal del backend → importe exacto. `null` si no es un decimal (un contrato roto se ve, no se adivina). */
export function parseDecimal(text: string): Decimal | null {
  const match = PATTERN.exec(text.trim());
  if (match === null) return null;
  const [, sign, whole, fraction = ""] = match;
  if (fraction.length > SCALE && /[1-9]/.test(fraction.slice(SCALE))) return null; // más precisión de la que existe
  const scaled = BigInt(whole) * FACTOR + BigInt(fraction.padEnd(SCALE, "0").slice(0, SCALE));
  return { units: sign === "-" ? -scaled : scaled };
}

/** Entero (unidades de una línea) → importe. Rechaza lo que no sea un entero finito. */
export function fromInteger(value: number): Decimal | null {
  if (!Number.isSafeInteger(value)) return null;
  return { units: BigInt(value) * FACTOR };
}

export const add = (a: Decimal, b: Decimal): Decimal => ({ units: a.units + b.units });
export const subtract = (a: Decimal, b: Decimal): Decimal => ({ units: a.units - b.units });

/** Importe × un número entero de unidades: exacto, sin escalado que perder. */
export function multiplyByCount(amount: Decimal, count: number): Decimal | null {
  if (!Number.isSafeInteger(count)) return null;
  return { units: amount.units * BigInt(count) };
}

export const isZero = (value: Decimal) => value.units === NOUGHT;
export const isNegative = (value: Decimal) => value.units < NOUGHT;
export const equals = (a: Decimal, b: Decimal) => a.units === b.units;

/** Importe → texto decimal del backend (4 decimales, con signo si lo tiene). */
export function toText(value: Decimal): string {
  const negative = value.units < NOUGHT;
  const absolute = negative ? -value.units : value.units;
  const whole = absolute / FACTOR;
  const fraction = (absolute % FACTOR).toString().padStart(SCALE, "0");
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}
