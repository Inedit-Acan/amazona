// Cómo se piden los agregados de ingresos (M45, ADR 0030). Solo construye rutas de LECTURA: nada de aquí escribe, y
// por eso vive aparte de `lib/api.ts` (que arrastra el resolutor de token y no se puede cargar en un test).

const DAY_MS = 86_400_000;

/** Periodos que ofrece el Panel (días naturales UTC, el de hoy incluido). */
export const REVENUE_PERIODS = [7, 14, 30] as const;
export const DEFAULT_REVENUE_DAYS = 30;

/** Entradas por página en el Panel; el backend admite hasta 200 (`GET /api/revenue/entries`). */
export const REVENUE_ENTRIES_PAGE_SIZE = 25;

/** `?dias=` → un periodo permitido. Cualquier otra cosa vuelve al de por defecto: nunca una ventana arbitraria. */
export function parseRevenueDays(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const days = Number(raw);
  return (REVENUE_PERIODS as readonly number[]).includes(days) ? days : DEFAULT_REVENUE_DAYS;
}

/** Ventana `[from, to)` en UTC: los últimos `days` días naturales, hoy incluido. `to` es exclusivo (el backend mide por
 * `occurred_at`, `from` inclusivo y `to` exclusivo). */
export interface RevenueWindow {
  from: string;
  to: string;
}

export function revenueWindow(now: number, days: number): RevenueWindow {
  const startOfToday = now - (((now % DAY_MS) + DAY_MS) % DAY_MS);
  const to = startOfToday + DAY_MS;
  return { from: new Date(to - days * DAY_MS).toISOString(), to: new Date(to).toISOString() };
}

export type RevenueResource = "summary" | "series" | "entries";

type Param = string | number | undefined | null;

/** `/api/revenue/<recurso>?…` con los parámetros en orden alfabético (la misma petición da siempre la misma URL). Los
 * vacíos no se envían. */
export function revenuePath(resource: RevenueResource, params: Record<string, Param> = {}): string {
  const query = new URLSearchParams();
  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    if (value === undefined || value === null || value === "") continue;
    query.set(key, String(value));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return `/api/revenue/${resource}${suffix}`;
}
