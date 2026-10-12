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
//
// SEGUNDO EJE (M46, ADR 0031): el ORIGEN del dinero (`mock`, `sandbox`, `real`: de qué adaptador salió el hecho), ortogonal
// a la procedencia de arriba. Un hecho `verified` lleva además su origen en el tipo (`Verified<T, O>`), y las cifras de
// orígenes distintos no se suman: `addVerified` no compila con dos orígenes literales distintos y lanza
// `MixedOriginError` cuando el origen viene de datos. El vocabulario de pantalla del origen (etiquetas, textos, «Varios
// orígenes», «Sin cobro», «Sin datos de origen») vive SOLO aquí: ningún componente escribe el suyo.

import { add as addDecimal, subtract as subtractDecimal, type Decimal } from "./decimal.ts";

export type Provenance = "verified" | "declared" | "planned" | "demo";

/** Las procedencias que no llevan origen de dinero: lo declarado, lo proyectado y lo inventado. */
export type OriginLess = Exclude<Provenance, "verified">;

/** Una cifra con su procedencia pegada. La procedencia va en el tipo, no en una convención. */
export interface Tagged<P extends OriginLess, T> {
  readonly provenance: P;
  readonly value: T;
}

// --- El origen del dinero (M46, ADR 0031) -------------------------------------------------------------------------

/** El vocabulario cerrado del backend (`provider_kind`). Es lo único que se acepta: lo demás no se completa nunca. */
export const ORIGINS = ["mock", "sandbox", "real"] as const;
export type Origin = (typeof ORIGINS)[number];

export const isOrigin = (value: unknown): value is Origin =>
  typeof value === "string" && (ORIGINS as readonly string[]).includes(value);

/** Un hecho verificado con su origen en el tipo. Dos orígenes distintos son dos magnitudes distintas. */
export interface Verified<T, O extends Origin = Origin> {
  readonly provenance: "verified";
  readonly origin: O;
  readonly value: T;
}

export type Declared<T> = Tagged<"declared", T>;
export type Planned<T> = Tagged<"planned", T>;
export type Demo<T> = Tagged<"demo", T>;

/** Un hecho verificado de un origen. Sin origen no hay hecho verificado: no existe `verified(x)` a secas. */
export const verified = <T, O extends Origin>(value: T, origin: O): Verified<T, O> => ({
  provenance: "verified",
  origin,
  value,
});
export const declared = <T>(value: T): Declared<T> => ({ provenance: "declared", value });
export const planned = <T>(value: T): Planned<T> => ({ provenance: "planned", value });
export const demo = <T>(value: T): Demo<T> => ({ provenance: "demo", value });

/** Suma de dos cifras de la misma procedencia. Mezclar procedencias **no compila**; los hechos verificados (que además
 * llevan origen) se suman con `addVerified`. */
export function add<P extends OriginLess>(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>): Tagged<P, Decimal> {
  return { provenance: a.provenance, value: addDecimal(a.value, b.value) };
}

/** Resta de dos cifras de la misma procedencia. Mezclar procedencias **no compila**. */
export function subtract<P extends OriginLess>(a: Tagged<P, Decimal>, b: Tagged<P, Decimal>): Tagged<P, Decimal> {
  return { provenance: a.provenance, value: subtractDecimal(a.value, b.value) };
}

/** Suma de una lista homogénea; una lista vacía no es cero, es `null` («sin datos»). */
export function total<P extends OriginLess>(values: Tagged<P, Decimal>[]): Tagged<P, Decimal> | null {
  if (values.length === 0) return null;
  return values.reduce((accumulated, current) => add(accumulated, current));
}

/** Dos orígenes distintos llegaron a una misma cifra: no existe esa cifra. */
export class MixedOriginError extends Error {
  constructor(a: Origin, b: Origin) {
    super(`No se pueden sumar hechos verificados de orígenes distintos (${a} y ${b}): son magnitudes distintas.`);
    this.name = "MixedOriginError";
  }
}

/** Suma de dos hechos verificados del MISMO origen. Con orígenes literales distintos no compila; con orígenes que
 * vienen de datos, lanza `MixedOriginError`: nunca devuelve una cifra que cruce orígenes. */
export function addVerified<O extends Origin>(a: Verified<Decimal, O>, b: Verified<Decimal, NoInfer<O>>): Verified<Decimal, O> {
  if (a.origin !== b.origin) throw new MixedOriginError(a.origin, b.origin);
  return verified(addDecimal(a.value, b.value), a.origin);
}

export function subtractVerified<O extends Origin>(
  a: Verified<Decimal, O>,
  b: Verified<Decimal, NoInfer<O>>,
): Verified<Decimal, O> {
  if (a.origin !== b.origin) throw new MixedOriginError(a.origin, b.origin);
  return verified(subtractDecimal(a.value, b.value), a.origin);
}

/** Lo que dicen los orígenes de un conjunto de hechos monetarios. Nunca se inventa uno que no está. */
export type OriginSummary =
  | { kind: "none" } // no hay ningún hecho monetario: no hay origen que decir
  | { kind: "single"; origin: Origin }
  | { kind: "multiple"; origins: Origin[] } // en orden alfabético
  | { kind: "unknown"; values: string[] }; // algún valor fuera del vocabulario: no se traduce a nada

export function summarizeOrigins(values: Iterable<unknown>): OriginSummary {
  const known = new Set<Origin>();
  const strange = new Set<string>();
  for (const value of values) {
    if (isOrigin(value)) known.add(value);
    else strange.add(String(value));
  }
  if (strange.size > 0) return { kind: "unknown", values: [...strange].sort() };
  if (known.size === 0) return { kind: "none" };
  const origins = [...known].sort();
  return origins.length === 1 ? { kind: "single", origin: origins[0] } : { kind: "multiple", origins };
}

/** Cómo se llama cada origen en pantalla. El origen describe al PROVEEDOR del hecho: no afirma nada del dinero. */
export const ORIGIN_LABEL: Record<Origin, string> = {
  mock: "Simulado",
  sandbox: "Entorno de pruebas",
  real: "Proveedor real",
};

export const ORIGIN_MEANING: Record<Origin, string> = {
  mock: "El hecho lo registró un adaptador simulado: ningún proveedor ni dinero de clientes intervino.",
  sandbox: "El hecho viene del entorno de pruebas de un proveedor: no es dinero de clientes.",
  real: "El hecho viene de un proveedor real. Es la procedencia del proveedor: no confirma que el dinero esté liquidado ni contabilizado.",
};

export const ORIGIN_MULTIPLE_LABEL = "Varios orígenes";
export const ORIGIN_NONE_LABEL = "Sin cobro";
export const ORIGIN_UNKNOWN_LABEL = "Sin datos de origen";

export function originLabel(summary: OriginSummary): string {
  switch (summary.kind) {
    case "single":
      return ORIGIN_LABEL[summary.origin];
    case "multiple":
      return ORIGIN_MULTIPLE_LABEL;
    case "none":
      return ORIGIN_NONE_LABEL;
    case "unknown":
      return ORIGIN_UNKNOWN_LABEL;
  }
}

export function originMeaning(summary: OriginSummary): string {
  switch (summary.kind) {
    case "single":
      return ORIGIN_MEANING[summary.origin];
    case "multiple":
      return `Hay hechos de ${summary.origins.map((origin) => ORIGIN_LABEL[origin]).join(", ")}: cada origen se enseña aparte y ninguna cifra los suma.`;
    case "none":
      return "No hay ningún cobro con dinero verificado: no hay origen que enseñar y no se inventa uno.";
    case "unknown":
      return "El backend devolvió un origen que esta pantalla no conoce: no se interpreta ni se completa.";
  }
}

/** El nombre de un origen aislado (`mock`, `sandbox`, `real`) o, si no es del vocabulario, «Sin datos de origen». */
export function originName(value: unknown): string {
  return originLabel(summarizeOrigins([value]));
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
    "Hecho de pago verificado y registrado por el backend (ADR 0030). Cada cifra lleva el origen (provider_kind) que el backend guardó en el hecho; un hecho verificado no es dinero liquidado.",
  declared:
    "Dato que alguien declaró y que el backend guarda con su fuente (una cotización de proveedor o una declaración manual). No es un pago comprobado.",
  planned:
    "Proyección calculada sobre los supuestos de un análisis económico. No ha ocurrido: es lo que el modelo espera si los supuestos se cumplen.",
  demo: "Dato inventado para la demostración. No procede de ninguna fuente.",
};
