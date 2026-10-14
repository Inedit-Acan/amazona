import { READ_ERROR_TEXT, READ_UNAVAILABLE_VALUE, READ_UNREAD_TEXT, unreadState, type ReadState } from "./read-state.ts";

// El estado de un BLOQUE del Director ejecutivo (M47, Commit 2): las cuatro lecturas de M46 más una quinta que NO es una
// lectura.
//
//   loaded       lectura válida, con contenido.
//   empty        lectura válida y no hay nada: es un hecho.
//   unread       existe una fuente potencial, pero este bloque todavía NO la ha leído (no se intentó). No se sabe nada.
//   error        se intentó leer y falló.
//   unavailable  hoy NO existe una fuente ni una capacidad que lo respalde. No es una lectura pendiente: el backend no lo tiene.
//
// `unread` y `unavailable` no se mezclan: el primero se resuelve conectando el bloque; el segundo, construyendo la capacidad.

export type UnavailableState = { kind: "unavailable"; reason: string };

export type BlockState<T = never> = ReadState<T> | UnavailableState;

export const unavailableState = (reason: string): UnavailableState => ({ kind: "unavailable", reason });

/** El bloque tiene una fuente potencial y aún no la ha leído. */
export const NOT_CONNECTED_YET = unreadState("Este bloque todavía no ha leído su fuente.");

export type BlockKind = BlockState<unknown>["kind"];

export interface BlockNotice {
  kind: Exclude<BlockKind, "loaded">;
  /** Lo que se enseña en lugar del dato. Nunca un 0, un `[]` ni «Sin datos» para lo que no se sabe. */
  label: string;
  detail: string;
}

/** Lo que dice un bloque que no tiene dato que enseñar. `loaded` no tiene aviso: enseña su contenido. */
export function blockNotice(state: BlockState<unknown>): BlockNotice | null {
  switch (state.kind) {
    case "loaded":
      return null;
    case "empty":
      return { kind: "empty", label: "Sin elementos", detail: "El backend respondió y no hay ninguno." };
    case "unread":
      return { kind: "unread", label: READ_UNREAD_TEXT, detail: state.reason };
    case "error":
      return { kind: "error", label: READ_ERROR_TEXT, detail: state.message };
    case "unavailable":
      return { kind: "unavailable", label: READ_UNAVAILABLE_VALUE, detail: state.reason };
  }
}
