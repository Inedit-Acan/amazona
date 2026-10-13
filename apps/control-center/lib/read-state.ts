import { settle } from "./revenue-view.ts";

// El resultado de una LECTURA, con su significado (M46, Commit 6).
//
// Una lectura que falla no es un dato de negocio. Antes, el Panel convertía el error de una lectura en `[]`
// (`.catch(() => [])`) y de ahí salían un «0 / 0 agentes», un «Nada esperando tu decisión» o unas ejecuciones de
// demostración haciéndose pasar por el log real. Aquí cada lectura es UNA de cuatro cosas, y ninguna se confunde con otra:
//
//   loaded  lectura válida, con contenido.
//   empty   lectura válida y la colección está vacía: es un HECHO (el backend dijo «no hay nada»). Solo aquí puede
//           enseñarse «0» o «Sin …», y solo si cero es semánticamente correcto.
//   unread  no existe una lectura válida porque NO SE INTENTÓ (un producto fuera del tope de lectura, o un dato que
//           depende de otra lectura que no está). No se sabe nada: ni «hay» ni «no hay».
//   error   se intentó y falló (4xx, 5xx, backend inaccesible o una respuesta que no tiene la forma esperada).
//
// Reutiliza `settle` (M45): no hay un segundo sistema de lectura. `stale` no existe porque el Panel se renderiza en
// servidor y no conserva datos previos: ante un error se usa `error`.
//
// Nota de vocabulario: el `UNREAD = "No se pudo leer"` de `revenue-view.ts` (M45) significa, en esta taxonomía, `error`.

export type ReadState<T> =
  | { kind: "loaded"; data: T }
  | { kind: "empty" }
  | { kind: "unread"; reason: string }
  | { kind: "error"; message: string };

/** Textos para el usuario. Ninguno nombra un estado HTTP, un `fetch failed`, un `ECONNREFUSED` ni una traza. */
export const READ_ERROR_TEXT = "No se pudieron cargar los datos";
export const READ_UNAVAILABLE_TEXT = "Datos no disponibles en este momento";
export const READ_UNREAD_TEXT = "Sin leer";
export const READ_UNAVAILABLE_VALUE = "No disponible";

/** El texto de un fallo de lectura de `subject` («los agentes»). **Nunca** repite el estado ni el detalle del backend. */
export function readErrorText(status: number | undefined, subject: string): string {
  if (status === 401) return "La sesión no es válida o ha caducado. Vuelve a iniciar sesión.";
  if (status === 403) return `Tu usuario no tiene permiso para ver ${subject}.`;
  // Concordancia: «el catálogo» / «el log» (singular) frente a «los agentes» / «las aprobaciones» (plural).
  return /^(el|la)\s/.test(subject) ? `No se pudo cargar ${subject}.` : `No se pudieron cargar ${subject}.`;
}

/** Lee una lista y la clasifica. Una respuesta que no es un array es un `error`, no una lista vacía: un contrato roto no
 * se interpreta como «no hay nada». */
export async function readList<T>(read: () => Promise<T[]>, subject: string): Promise<ReadState<T[]>> {
  const settled = await settle(read, (status) => readErrorText(status, subject));
  if (!settled.ok) return { kind: "error", message: settled.message };
  if (!Array.isArray(settled.data)) return { kind: "error", message: readErrorText(undefined, subject) };
  return settled.data.length === 0 ? { kind: "empty" } : { kind: "loaded", data: settled.data };
}

export const unreadState = (reason: string): ReadState<never> => ({ kind: "unread", reason });

/** La lista de una lectura válida (`[]` solo si el backend dijo que estaba vacía); `null` si no hay lectura válida. */
export function listOf<T>(state: ReadState<T[]>): T[] | null {
  if (state.kind === "loaded") return state.data;
  if (state.kind === "empty") return [];
  return null;
}

/** Hay una lectura válida (con o sin contenido). */
export const isUsable = <T>(state: ReadState<T>): state is Extract<ReadState<T>, { kind: "loaded" | "empty" }> =>
  state.kind === "loaded" || state.kind === "empty";

/** De dos o más lecturas, la peor: `error` antes que `unread`, y `null` si todas son válidas. */
export function worstOf(states: ReadonlyArray<ReadState<unknown>>): "error" | "unread" | null {
  if (states.some((state) => state.kind === "error")) return "error";
  if (states.some((state) => state.kind === "unread")) return "unread";
  return null;
}
