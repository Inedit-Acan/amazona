/** `Idempotency-Key` de las peticiones con efecto (hardening pre-M44, ADR 0025).
 *
 * El backend la exige en cuanto el despliegue puede tocar algo fuera del sistema (428 si falta) y, cuando llega,
 * garantiza que repetir **esa misma petición** no repite su efecto. Cada llamada de `api.*` lleva una clave nueva:
 * eso cubre la exigencia del backend y cualquier reintento de la misma llamada, pero **no** un segundo clic, que es
 * otra llamada con otra clave. Para que un formulario sea a prueba de doble clic tiene que conservar su clave y
 * pasarla en `headers` hasta que la operación termine; este módulo no lo hace por él.
 *
 * Las rutas que no usan la clave la ignoran. */

export const IDEMPOTENCY_HEADER = "Idempotency-Key";

export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

/** La cabecera que hay que añadir a una petición, o nada si no procede: solo los `POST`, y solo si quien llama no
 * puso la suya. */
export function withIdempotencyKey(
  init?: { method?: string; headers?: HeadersInit },
  makeKey: () => string = newIdempotencyKey,
): Record<string, string> {
  if ((init?.method ?? "GET").toUpperCase() !== "POST") return {};
  if (new Headers(init?.headers).has(IDEMPOTENCY_HEADER)) return {};
  return { [IDEMPOTENCY_HEADER]: makeKey() };
}
