/** El backend guarda todas las fechas en UTC y, con SQLite, las devuelve sin sufijo de
 * zona («2026-09-21T21:49:34»): `new Date()` las tomaría como hora local y las
 * desplazaría. Aquí se interpretan como UTC; si ya traen zona se respetan. */
export function parseUtc(value: string): number {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`).getTime();
}

/** Mismo día natural en la zona local del navegador. */
export function isSameLocalDay(a: number, b: number): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return da.getFullYear() === db.getFullYear() && da.getMonth() === db.getMonth() && da.getDate() === db.getDate();
}

/** «en 3 h», «en 25 min», «hace 2 h»: distancia legible entre dos instantes. */
export function relativeTime(target: number, now: number): string {
  const diffMs = target - now;
  const abs = Math.abs(diffMs);
  const minutes = Math.round(abs / 60_000);
  const text =
    minutes < 1 ? "menos de 1 min" : minutes < 60 ? `${minutes} min` : abs < 48 * 3_600_000 ? `${Math.round(abs / 3_600_000)} h` : `${Math.round(abs / 86_400_000)} días`;
  return diffMs >= 0 ? `en ${text}` : `hace ${text}`;
}
