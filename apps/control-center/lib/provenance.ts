// De dónde sale cada cifra, y qué se puede hacer con ella (M45, Commit 10).
//
// El CFO enseña a la vez cuatro clases de información, y confundirlas es el error más caro que puede cometer esta
// aplicación. Así que la procedencia no es una etiqueta que se pinta al final: es parte del TIPO de cada cifra, y el
// compilador impide mezclarlas.
//
//   verified  un hecho que el backend registró      (el registro de ingresos verificados, ADR 0030)
//   declared  un dato que alguien declaró, con fuente (el coste de una línea de pedido: cotización o declaración)
//   planned   una proyección sobre supuestos         (los análisis económicos)
//   demo      un dato inventado para la demostración
//
// `add` y `subtract` solo aceptan dos cifras de la MISMA procedencia: sumar un hecho con una proyección no compila.
// La única combinación permitida es la del margen de contribución declarado, que vive en `cfo-margin.ts`, se declara
// ahí de forma explícita y degrada el resultado a `declared` — porque un resultado nunca puede ser más fiable que el
// menos fiable de sus ingredientes.

import { add as addDecimal, subtract as subtractDecimal, type Decimal } from "./decimal.ts";

export type Provenance = "verified" | "declared" | "planned" | "demo";

/** Una cifra con su procedencia pegada. La procedencia va en el tipo, no en una convención. */
export interface Tagged<P extends Provenance, T> {
  readonly provenance: P;
  readonly value: T;
}

export type Verified<T> = Tagged<"verified", T>;
export type Declared<T> = Tagged<"declared", T>;
export type Planned<T> = Tagged<"planned", T>;
export type Demo<T> = Tagged<"demo", T>;

export const verified = <T>(value: T): Verified<T> => ({ provenance: "verified", value });
export const declared = <T>(value: T): Declared<T> => ({ provenance: "declared", value });
export const planned = <T>(value: T): Planned<T> => ({ provenance: "planned", value });
export const demo = <T>(value: T): Demo<T> => ({ provenance: "demo", value });

/** Suma de dos cifras de la misma procedencia. Mezclar procedencias **no compila**. */
export function add<P extends Provenance>(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>): Tagged<P, Decimal> {
  return { provenance: a.provenance, value: addDecimal(a.value, b.value) };
}

/** Resta de dos cifras de la misma procedencia. Mezclar procedencias **no compila**. */
export function subtract<P extends Provenance>(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>): Tagged<P, Decimal> {
  return { provenance: a.provenance, value: subtractDecimal(a.value, b.value) };
}

/** Suma de una lista homogénea; una lista vacía no es cero, es `null` («sin datos»). */
export function total<P extends Provenance>(values: Tagged<P, Decimal>[]): Tagged<P, Decimal> | null {
  if (values.length === 0) return null;
  return values.reduce((accumulated, current) => add(accumulated, current));
}

/** Cómo se llama cada procedencia en pantalla, y qué promete. */
export const PROVENANCE_LABEL: Record<Provenance, string> = {
  verified: "Registro verificado",
  declared: "Declarado",
  planned: "Proyección (PLAN)",
  demo: "Demostración",
};

export const PROVENANCE_MEANING: Record<Provenance, string> = {
  verified:
    "Hecho de pago verificado y registrado por el backend (ADR 0030). No dice si la operación fue simulada: el registro todavía no guarda esa procedencia.",
  declared:
    "Dato que alguien declaró y que el backend guarda con su fuente (una cotización de proveedor o una declaración manual). No es un pago comprobado.",
  planned:
    "Proyección calculada sobre los supuestos de un análisis económico. No ha ocurrido: es lo que el modelo espera si los supuestos se cumplen.",
  demo: "Dato inventado para la demostración. No procede de ninguna fuente.",
};
