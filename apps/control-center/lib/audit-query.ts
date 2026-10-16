// La PETICIÓN de `GET /api/audit` (M47, micro-commit 5B). El backend (micro-commit 5A) admite, además del filtro de siempre, orden,
// límite y un cursor; aquí se arma la ruta con opciones tipadas y `URLSearchParams`, nunca concatenando texto a mano: un `+` de un
// desplazamiento horario (`+02:00`) sin codificar llegaría como un espacio y sería un instante inválido (422).
//
// Sin opciones, la ruta es `/api/audit`: la petición de siempre (ascendente, 500 filas, las más antiguas).

export type AuditOrder = "asc" | "desc";

/** El tope de filas por petición del backend. */
export const AUDIT_MAX_LIMIT = 500;

export interface AuditQuery {
  /** El filtro de siempre: solo las entradas de esa correlación. */
  correlationId?: string;
  /** `desc` = lo más reciente primero (con `limit`, las N más recientes). Sin él, el backend responde ascendente. */
  order?: AuditOrder;
  /** 1..500. Sin él, 500. */
  limit?: number;
  /** Instante ISO-8601 con fecha y hora (sin zona = UTC); inclusivo. */
  since?: string;
  /** Cursor `<created_at>,<id>` de la última fila recibida; solo las filas estrictamente anteriores. */
  before?: string;
}

/** `/api/audit?…` con los parámetros siempre en el mismo orden. Una opción inválida es un error AQUÍ (no se envía una petición que el
 * backend rechazaría ni se corrige en silencio). `since` y `before` vacíos sí se envían: el backend los rechaza con un 422. La firma
 * antigua `listAudit(correlationId)` sigue valiendo (un texto es el `correlationId`). */
export function auditPath(options?: AuditQuery | string): string {
  const { correlationId, order, limit, since, before }: AuditQuery = typeof options === "string" ? { correlationId: options } : (options ?? {});
  if (order !== undefined && order !== "asc" && order !== "desc") throw new RangeError(`order debe ser "asc" o "desc", no ${JSON.stringify(order)}`);
  if (limit !== undefined && !(Number.isInteger(limit) && limit >= 1 && limit <= AUDIT_MAX_LIMIT)) {
    throw new RangeError(`limit debe ser un entero entre 1 y ${AUDIT_MAX_LIMIT}, no ${String(limit)}`);
  }
  const query = new URLSearchParams();
  if (correlationId) query.set("correlation_id", correlationId);
  if (order !== undefined) query.set("order", order);
  if (limit !== undefined) query.set("limit", String(limit));
  if (since !== undefined) query.set("since", since);
  if (before !== undefined) query.set("before", before);
  return query.size > 0 ? `/api/audit?${query.toString()}` : "/api/audit";
}
