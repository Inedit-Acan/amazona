/**
 * Qué decir de la fuente de una tasa de cambio (Milestone 42, ADR 0020).
 *
 * Una tasa que sale de las referencias del BCE se reconoce por el prefijo `ecb:` de
 * su fuente, que solo escribe el refresco. No es una cotización: el BCE las publica
 * «solo con fines informativos» y la licencia exige citarlo. Esa advertencia y esa
 * atribución viajan con el cálculo hasta la pantalla.
 */

export const ECB_SOURCE_PREFIX = "ecb:";

export interface FxSourceNotice {
  /** Cómo se llama la fuente en pantalla. */
  label: string;
  /** La atribución que exige la licencia del BCE. */
  attribution: string;
  /** Lo que la tasa no es. */
  warning: string;
}

const ECB_NOTICE: FxSourceNotice = {
  label: "referencia BCE",
  attribution: "Fuente: Banco Central Europeo (BCE), tipos de cambio de referencia del euro.",
  warning:
    "Referencia informativa del BCE: no es la tasa transaccional que aplica un banco o un procesador de pagos.",
};

export function isEcbSource(source: string): boolean {
  return source.startsWith(ECB_SOURCE_PREFIX);
}

/** El aviso de una fuente que lo requiere, o `null` si no lo hay (una tasa declarada). */
export function fxSourceNotice(source: string): FxSourceNotice | null {
  return isEcbSource(source) ? ECB_NOTICE : null;
}

/** El nombre de la fuente para una línea de conversión. */
export function fxSourceLabel(source: string): string {
  return fxSourceNotice(source)?.label ?? source;
}

/** La fecha de ingestión como `AAAA-MM-DD`, o `null` si la conversión no la guardó. */
export function ingestedOn(ingestedAt: string | null | undefined): string | null {
  return ingestedAt ? ingestedAt.slice(0, 10) : null;
}

/** Los avisos distintos de un conjunto de conversiones, sin repetir el mismo. */
export function fxNotices(sources: readonly string[]): FxSourceNotice[] {
  const seen = new Map<string, FxSourceNotice>();
  for (const source of sources) {
    const notice = fxSourceNotice(source);
    if (notice) seen.set(notice.label, notice);
  }
  return [...seen.values()];
}

export interface RateLike {
  source: string;
  effective_date: string;
  ingested_at?: string | null;
}

export interface EcbSummary {
  count: number;
  latestEffectiveDate: string;
  latestIngestedAt: string | null;
  notice: FxSourceNotice;
}

/**
 * Separa lo que una persona declaró de lo que trajo el refresco del BCE. Las
 * referencias del BCE son decenas de filas por refresco: mezcladas en la lista de
 * tasas declaradas taparían las que alguien escribió a mano.
 */
export function splitRates<T extends RateLike>(rates: readonly T[]): {
  declared: T[];
  ecb: EcbSummary | null;
} {
  const declared = rates.filter((rate) => !isEcbSource(rate.source));
  const fromEcb = rates.filter((rate) => isEcbSource(rate.source));
  if (fromEcb.length === 0) return { declared, ecb: null };
  const latest = fromEcb.reduce((a, b) => (b.effective_date > a.effective_date ? b : a));
  const ingested = fromEcb
    .map((rate) => rate.ingested_at ?? null)
    .filter((value): value is string => value !== null)
    .sort()
    .at(-1) ?? null;
  return {
    declared,
    ecb: {
      count: fromEcb.length,
      latestEffectiveDate: latest.effective_date,
      latestIngestedAt: ingested,
      notice: ECB_NOTICE,
    },
  };
}
